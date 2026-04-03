"""Tests for the Cargo publish API (PUT /api/v1/crates/new).

NOTE: The test helpers (build_publish_metadata, cargo_publish) reuse
pulp_rust's own extract_cargo_toml / extract_dependencies to build the
publish request — the same code the server uses to process it.  The index
fidelity tests below validate that code path by comparing Pulp's index
output against independently-fetched crates.io data.  If those app
functions ever produce wrong results, these fidelity tests are what will
catch it.  Other test modules (auth, yank) also depend on the same helpers,
so keep these fidelity checks passing.
"""

from pulp_rust.tests.functional.utils import (
    assert_index_entry_matches_upstream,
    build_publish_metadata,
    cargo_publish,
    download_crate_from_upstream,
    get_index_entry,
)


def test_cargo_publish_and_index_fidelity(
    delete_orphans_pre,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    upstream_index_entry,
):
    """Publish a crate via the Cargo publish API and verify the index matches crates.io."""
    crate_name = "serde"
    crate_version = "1.0.210"

    crate_path, cksum = download_crate_from_upstream(crate_name, crate_version)
    with open(crate_path, "rb") as f:
        crate_bytes = f.read()

    metadata = build_publish_metadata(crate_path, crate_name, crate_version)

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_publish(base, metadata, crate_bytes)
    assert response.status_code == 200, response.text
    result = response.json()
    assert "warnings" in result

    # Fetch the index from Pulp and compare against crates.io
    pulp_entry = get_index_entry(base, "se/rd/serde", "1.0.210")
    assert_index_entry_matches_upstream(pulp_entry, upstream_index_entry)


def test_cargo_publish_duplicate_rejected(
    delete_orphans_pre,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publishing the same crate version twice should be rejected."""
    crate_name = "serde"
    crate_version = "1.0.210"

    crate_path, _ = download_crate_from_upstream(crate_name, crate_version)
    with open(crate_path, "rb") as f:
        crate_bytes = f.read()

    metadata = build_publish_metadata(crate_path, crate_name, crate_version)

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    # First publish should succeed
    response = cargo_publish(base, metadata, crate_bytes)
    assert response.status_code == 200, response.text

    # Second publish of the same version should be rejected
    response = cargo_publish(base, metadata, crate_bytes)
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert any("already uploaded" in e["detail"] for e in errors)


def test_cargo_publish_ignores_tampered_json_metadata(
    delete_orphans_pre,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    upstream_index_entry,
):
    """Tampered JSON metadata should be ignored in favor of the Cargo.toml in the tarball.

    See: https://github.com/rust-lang/cargo/issues/14492
    """
    crate_name = "serde"
    crate_version = "1.0.210"

    crate_path, cksum = download_crate_from_upstream(crate_name, crate_version)
    with open(crate_path, "rb") as f:
        crate_bytes = f.read()

    # Build correct metadata, then tamper with it
    metadata = build_publish_metadata(crate_path, crate_name, crate_version)
    metadata["deps"] = [
        {
            "name": "evil-dep",
            "version_req": "^1.0",
            "features": [],
            "optional": False,
            "default_features": True,
            "target": None,
            "kind": "normal",
            "registry": None,
            "explicit_name_in_toml": None,
        }
    ]
    metadata["features"] = {"backdoor": ["evil-dep"]}
    metadata["links"] = "tampered-link"

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_publish(base, metadata, crate_bytes)
    assert response.status_code == 200, response.text

    # The index entry should match crates.io (i.e. the Cargo.toml), not the tampered JSON
    pulp_entry = get_index_entry(base, "se/rd/serde", "1.0.210")
    assert_index_entry_matches_upstream(pulp_entry, upstream_index_entry)


def test_cargo_publish_octet_stream_content_type(
    delete_orphans_pre,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publish should accept Content-Type: application/octet-stream.

    Current Cargo omits Content-Type entirely; a proposed upstream fix
    will send application/octet-stream instead.  The server must accept both.
    """
    crate_name = "serde"
    crate_version = "1.0.210"

    crate_path, _ = download_crate_from_upstream(crate_name, crate_version)
    with open(crate_path, "rb") as f:
        crate_bytes = f.read()

    metadata = build_publish_metadata(crate_path, crate_name, crate_version)

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_publish(base, metadata, crate_bytes, content_type="application/octet-stream")
    assert response.status_code == 200, response.text


def test_cargo_publish_uploads_disabled(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publishing to a distribution with allow_uploads=False should be rejected."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=False)
    base = cargo_registry_url(distribution.base_path)

    metadata = {"name": "foo", "vers": "0.1.0", "deps": [], "features": {}}
    response = cargo_publish(base, metadata, b"fake-crate-data")
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("does not allow uploads" in e["detail"] for e in errors)
