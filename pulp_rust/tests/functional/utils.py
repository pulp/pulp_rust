import json

import aiohttp
import asyncio
from dataclasses import dataclass

CRATES_IO_URL = "sparse+https://index.crates.io/"

# Fields from the sparse index that Pulp should faithfully reproduce.
# "yanked" is excluded because it depends on per-repo yank state, not upstream.
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
