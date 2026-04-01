"""Tests for Cargo pull-through caching via the sparse index proxy."""

from urllib.parse import urljoin

from pulp_rust.tests.functional.utils import download_file


def test_pull_through_sparse_index(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Verify that the sparse index metadata is proxied from the upstream remote."""
    remote = rust_remote_factory(url="sparse+https://index.crates.io/")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # Request sparse index metadata for a well-known small crate
    # The sparse index path for "itoa" (4 chars) is "it/oa/itoa"
    index_url = urljoin(cargo_registry_url(distribution.base_path), "it/oa/itoa")
    downloaded = download_file(index_url)
    assert downloaded.response_obj.status == 200

    # The response should be newline-delimited JSON
    body = downloaded.body.decode("utf-8")
    assert body.strip()
    # Each line should be valid JSON containing the crate name
    for line in body.strip().split("\n"):
        assert '"name":"itoa"' in line or '"name": "itoa"' in line


def test_pull_through_crate_download(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_repo_api_client,
    monitor_task,
    cargo_registry_url,
):
    """Verify that .crate files are pulled through and cached."""
    remote = rust_remote_factory(url="sparse+https://index.crates.io/")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # Download a .crate file through Pulp (goes via Cargo API, redirects to content app)
    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    downloaded = download_file(pulp_unit_url)
    assert downloaded.response_obj.status == 200

    # Add cached content to the repository
    monitor_task(
        rust_repo_api_client.add_cached_content(
            repository.pulp_href, {"remote": remote.pulp_href}
        ).task
    )

    repository = rust_repo_api_client.read(repository.pulp_href)
    assert not repository.latest_version_href.endswith("/versions/0/")
