"""Tests for Cargo pull-through caching via the sparse index proxy."""

import hashlib
from urllib.parse import urljoin

import pytest

from pulp_rust.tests.functional.utils import download_file

CRATES_IO_URL = "sparse+https://index.crates.io/"


def test_pull_through_sparse_index(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Verify that the sparse index metadata is proxied from the upstream remote."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
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


@pytest.mark.parametrize("policy", ["on_demand", "streamed"])
def test_pull_through_crate_download(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    policy,
):
    """Verify that .crate files can be downloaded via pull-through."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy=policy)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    downloaded = download_file(pulp_unit_url)
    assert downloaded.response_obj.status == 200
    assert len(downloaded.body) > 0


@pytest.mark.parametrize("policy", ["on_demand", "streamed"])
def test_pull_through_repeated_download(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    policy,
):
    """Downloading the same crate twice should work for both policies."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy=policy)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)

    first = download_file(pulp_unit_url)
    assert first.response_obj.status == 200

    second = download_file(pulp_unit_url)
    assert second.response_obj.status == 200

    # Both downloads should return identical content
    assert hashlib.sha256(first.body).hexdigest() == hashlib.sha256(second.body).hexdigest()


def test_pull_through_on_demand_creates_content(
    delete_orphans_pre,
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_content_api_client,
    cargo_registry_url,
):
    """on_demand pull-through should create a RustContent record and cache the artifact."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy="on_demand")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    downloaded = download_file(pulp_unit_url)
    assert downloaded.response_obj.status == 200

    # A RustContent record should have been created
    content_response = rust_content_api_client.list(name="itoa", vers="1.0.0")
    assert content_response.count == 1


def test_pull_through_on_demand_add_cached_content(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_repo_api_client,
    monitor_task,
    cargo_registry_url,
):
    """on_demand: add_cached_content should add pulled-through content to a new repo version."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy="on_demand")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # Download a crate to trigger caching
    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    download_file(pulp_unit_url)

    # Add cached content to the repository
    monitor_task(
        rust_repo_api_client.add_cached_content(
            repository.pulp_href, {"remote": remote.pulp_href}
        ).task
    )

    repository = rust_repo_api_client.read(repository.pulp_href)
    assert not repository.latest_version_href.endswith("/versions/0/")


def test_pull_through_on_demand_serves_from_cache_without_remote(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_distro_api_client,
    rust_repo_api_client,
    monitor_task,
    cargo_registry_url,
):
    """on_demand: after caching, content should be served even after removing the remote."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy="on_demand")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    first_download = download_file(pulp_unit_url)
    first_checksum = hashlib.sha256(first_download.body).hexdigest()

    # Add cached content to the repository
    monitor_task(
        rust_repo_api_client.add_cached_content(
            repository.pulp_href, {"remote": remote.pulp_href}
        ).task
    )

    # Remove the remote from the distribution
    monitor_task(
        rust_distro_api_client.partial_update(distribution.pulp_href, {"remote": None}).task
    )

    # Content should still be served from cache
    second_download = download_file(pulp_unit_url)
    assert second_download.response_obj.status == 200
    assert hashlib.sha256(second_download.body).hexdigest() == first_checksum


def test_pull_through_streamed_no_content_created(
    delete_orphans_pre,
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_content_api_client,
    cargo_registry_url,
):
    """streamed: pull-through should NOT create a RustContent record."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy="streamed")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    unit_path = "api/v1/crates/itoa/1.0.0/download"
    pulp_unit_url = urljoin(cargo_registry_url(distribution.base_path), unit_path)
    downloaded = download_file(pulp_unit_url)
    assert downloaded.response_obj.status == 200

    # No RustContent record should have been created
    content_response = rust_content_api_client.list(name="itoa", vers="1.0.0")
    assert content_response.count == 0


def test_pull_through_multiple_crates_on_demand(
    delete_orphans_pre,
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_content_api_client,
    rust_repo_api_client,
    monitor_task,
    cargo_registry_url,
):
    """on_demand: downloading multiple crates should cache all of them."""
    remote = rust_remote_factory(url=CRATES_IO_URL, policy="on_demand")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    base = cargo_registry_url(distribution.base_path)
    download_file(urljoin(base, "api/v1/crates/itoa/1.0.0/download"))
    download_file(urljoin(base, "api/v1/crates/cfg-if/1.0.0/download"))

    # Both should have content records
    assert rust_content_api_client.list(name="itoa", vers="1.0.0").count == 1
    assert rust_content_api_client.list(name="cfg-if", vers="1.0.0").count == 1

    # add_cached_content should pick up both
    monitor_task(
        rust_repo_api_client.add_cached_content(
            repository.pulp_href, {"remote": remote.pulp_href}
        ).task
    )

    repository = rust_repo_api_client.read(repository.pulp_href)
    assert not repository.latest_version_href.endswith("/versions/0/")
