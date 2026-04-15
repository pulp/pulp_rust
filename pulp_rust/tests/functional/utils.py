import hashlib
import json
import struct
import tempfile

import aiohttp
import asyncio
import requests
from dataclasses import dataclass

from pulp_rust.app.auth import STUB_TOKEN
from pulp_rust.app.utils import extract_cargo_toml, extract_dependencies

CRATES_IO_URL = "sparse+https://index.crates.io/"
CRATES_IO_DOWNLOAD_URL = "https://static.crates.io/crates/"
CARGO_AUTH_HEADERS = {"Authorization": STUB_TOKEN}

# Fields from the sparse index that Pulp should faithfully reproduce.
# "yanked" is excluded because it depends on per-repo yank state, not upstream.
# "v" is excluded because it's a schema version marker that older crates.io entries omit
# (it defaults to 1 when absent).
INDEX_FIELDS_TO_COMPARE = ("name", "vers", "deps", "cksum", "features", "links")


@dataclass
class Download:
    """Class for representing a downloaded file."""

    body: bytes
    response_obj: aiohttp.ClientResponse

    def __init__(self, body, response_obj):
        self.body = body
        self.response_obj = response_obj


# --- Low-level HTTP helpers ---


def cargo_api_request(method, url, **kwargs):
    """Make an HTTP request to Cargo API endpoints, ignoring .netrc.

    CI environments have a .netrc file that the ``requests`` library uses to
    silently inject Basic auth headers, which interferes with tests that verify
    unauthenticated or wrong-token requests are rejected.
    """
    kwargs.setdefault("verify", False)
    with requests.Session() as s:
        s.trust_env = False
        return s.request(method, url, **kwargs)


def download_file(url, auth=None, headers=None):
    """Download a file.

    :param url: str URL to the file to download
    :param auth: `aiohttp.BasicAuth` containing basic auth credentials
    :param headers: dict of headers to send with the GET request
    :return: Download
    """
    return asyncio.run(_download_file(url, auth=auth, headers=headers))


async def _download_file(url, auth=None, headers=None):
    async with aiohttp.ClientSession(auth=auth, raise_for_status=True) as session:
        async with session.get(url, verify_ssl=False, headers=headers) as response:
            return Download(body=await response.read(), response_obj=response)


# --- Cargo publish helpers ---


def _build_cargo_publish_body(metadata, crate_bytes):
    """Build the binary request body that ``cargo publish`` sends.

    Format (per Cargo registry web API spec):
        4 bytes: JSON metadata length (little-endian u32)
        N bytes: JSON metadata (UTF-8)
        4 bytes: .crate file length (little-endian u32)
        M bytes: .crate file (binary)
    """
    json_bytes = json.dumps(metadata).encode("utf-8")
    return (
        struct.pack("<I", len(json_bytes))
        + json_bytes
        + struct.pack("<I", len(crate_bytes))
        + crate_bytes
    )


def cargo_publish(url, metadata, crate_bytes, content_type=None):
    """Send a publish request mimicking ``cargo publish``.

    The body is a custom binary format (length-prefixed JSON metadata +
    .crate file), not valid JSON.  The *content_type* parameter controls the
    Content-Type header: ``None`` omits it (current Cargo behaviour) and
    ``"application/octet-stream"`` matches the fix proposed upstream.
    """
    body = _build_cargo_publish_body(metadata, crate_bytes)
    headers = dict(CARGO_AUTH_HEADERS)
    if content_type is not None:
        headers["Content-Type"] = content_type
    return cargo_api_request(
        "PUT",
        f"{url}api/v1/crates/new",
        data=body,
        headers=headers,
    )


def minimal_publish_request(url, headers=None):
    """Send a minimal publish request to the Cargo publish endpoint.

    Builds a tiny fake crate body — useful for testing auth and validation
    without needing a real .crate file.
    """
    metadata = {"name": "fake", "vers": "0.0.1", "deps": [], "features": {}}
    return cargo_api_request(
        "PUT",
        f"{url}api/v1/crates/new",
        data=_build_cargo_publish_body(metadata, b"fake"),
        headers=headers or {},
    )


def build_publish_metadata(crate_path, crate_name, crate_version):
    """Extract metadata from a .crate file and format it for the publish API.

    Cargo uses "version_req" (not "req") and "explicit_name_in_toml" (not "package")
    per the Cargo registry web API spec.
    """
    with open(crate_path, "rb") as f:
        cargo_toml = extract_cargo_toml(f, crate_name, crate_version)
    deps = extract_dependencies(cargo_toml)

    return {
        "name": crate_name,
        "vers": crate_version,
        "deps": [
            {
                "name": dep["name"],
                "version_req": dep["req"],
                "features": dep["features"],
                "optional": dep["optional"],
                "default_features": dep["default_features"],
                "target": dep["target"],
                "kind": dep["kind"],
                "registry": dep.get("registry"),
                "explicit_name_in_toml": dep.get("package"),
            }
            for dep in deps
        ],
        "features": cargo_toml.get("features", {}),
        "links": cargo_toml.get("package", {}).get("links"),
        "rust_version": cargo_toml.get("package", {}).get("rust-version"),
    }


# --- Index helpers ---


def parse_index_entry(body, version):
    """Find and return the index entry for a specific version from newline-delimited JSON."""
    for line in body.strip().split("\n"):
        entry = json.loads(line)
        if entry["vers"] == version:
            return entry
    return None


def get_index_entry(url, sparse_path, version):
    """Fetch a sparse index (from any base URL) and return the entry for a single version.

    Works for both upstream registries (e.g. https://index.crates.io/) and
    Pulp-served registries.
    """
    from urllib.parse import urljoin

    full_url = urljoin(url, sparse_path)
    downloaded = download_file(full_url)
    assert downloaded.response_obj.status == 200
    entry = parse_index_entry(downloaded.body.decode("utf-8"), version)
    if entry is None:
        raise AssertionError(f"Version {version} not found in index at {full_url}")
    return entry


# --- Upstream helpers ---


def download_crate_from_upstream(name, version):
    """Download a .crate file directly from crates.io and return (path, sha256)."""
    url = f"{CRATES_IO_DOWNLOAD_URL}{name}/{name}-{version}.crate"
    downloaded = download_file(url)
    assert downloaded.response_obj.status == 200

    tmp = tempfile.NamedTemporaryFile(suffix=".crate", delete=False)
    tmp.write(downloaded.body)
    tmp.flush()

    cksum = hashlib.sha256(downloaded.body).hexdigest()
    return tmp.name, cksum


# --- Assertion helpers ---


def assert_index_entry_matches_upstream(pulp_entry, upstream_entry):
    """Assert that a Pulp-served index entry matches the upstream for all stored fields."""
    for field in INDEX_FIELDS_TO_COMPARE:
        if field == "deps":

            def sort_key(d):
                return (
                    d["name"],
                    d.get("kind", ""),
                    d.get("req", ""),
                    d.get("target") or "",
                )

            pulp_deps = sorted(pulp_entry["deps"], key=sort_key)
            upstream_deps = sorted(upstream_entry["deps"], key=sort_key)
            assert (
                pulp_deps == upstream_deps
            ), f"deps mismatch:\n  pulp={pulp_deps}\n  upstream={upstream_deps}"
        else:
            assert pulp_entry.get(field) == upstream_entry.get(field), (
                f"{field} mismatch: pulp={pulp_entry.get(field)!r} "
                f"upstream={upstream_entry.get(field)!r}"
            )

    # Also compare optional fields that may be present
    for field in ("features2", "rust_version"):
        if field in upstream_entry:
            assert pulp_entry.get(field) == upstream_entry[field], (
                f"{field} mismatch: pulp={pulp_entry.get(field)!r} "
                f"upstream={upstream_entry[field]!r}"
            )
