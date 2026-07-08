"""Functional tests for Cargo yank/unyank support."""

import hashlib
import json
from urllib.parse import urljoin

import pytest

from pulp_rust.tests.functional.utils import (
    CRATES_IO_URL,
    cargo_unyank,
    cargo_yank,
    download_file,
    get_index_entry,
)


@pytest.fixture
def admin_auth_headers(rust_token_factory, pulp_admin_user):
    """Create a Cargo token for the admin user and return auth headers."""
    token = rust_token_factory(pulp_admin_user)
    return {"Authorization": token.token}


def get_all_index_entries(cargo_url, sparse_path):
    """Fetch the sparse index and return all entries."""
    index_url = urljoin(cargo_url, sparse_path)
    downloaded = download_file(index_url)
    body = downloaded.body.decode("utf-8")
    return [json.loads(line) for line in body.strip().split("\n")]


@pytest.fixture
def populated_repo(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_repo_api_client,
    rust_distro_api_client,
    monitor_task,
    cargo_registry_url,
):
    """Create a repo with itoa 1.0.0 and 1.0.1 cached locally."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )
    base_url = cargo_registry_url(distribution.base_path)

    # Pull through two versions to cache them
    for version in ("1.0.0", "1.0.1"):
        unit_path = f"api/v1/crates/itoa/{version}/download"
        download_file(urljoin(base_url, unit_path))

    # Detach remote from distribution so index is served from local content
    monitor_task(
        rust_distro_api_client.partial_update(distribution.pulp_href, {"remote": None}).task
    )

    return {
        "repository": rust_repo_api_client.read(repository.pulp_href),
        "distribution": rust_distro_api_client.read(distribution.pulp_href),
        "base_url": base_url,
    }


# --- Cargo API happy path ---


def test_yank_happy_path(populated_repo, admin_auth_headers):
    """Yanking a crate version via the Cargo API should mark it as yanked in the index."""
    base_url = populated_repo["base_url"]

    # Verify initially not yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry is not None
    assert entry["yanked"] is False

    # Yank via Cargo API
    response = cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Verify now yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is True


def test_unyank_happy_path(populated_repo, admin_auth_headers):
    """Unyanking a crate version should restore it in the index."""
    base_url = populated_repo["base_url"]

    # Yank first
    cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)

    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is True

    # Unyank
    response = cargo_unyank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Verify no longer yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is False


# --- Error cases ---


def test_yank_nonexistent_package(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    admin_auth_headers,
):
    """Yanking a crate that doesn't exist in the repo should fail."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base_url = cargo_registry_url(distribution.base_path)

    response = cargo_yank(base_url, "nonexistent", "0.0.0", headers=admin_auth_headers)
    assert response.status_code == 404


def test_yank_no_repository(
    rust_distribution_factory,
    cargo_registry_url,
    admin_auth_headers,
):
    """Yanking on a distribution with no repository should 404."""
    distribution = rust_distribution_factory()
    base_url = cargo_registry_url(distribution.base_path)

    response = cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)
    assert response.status_code == 404


# --- Idempotency ---


def test_yank_idempotent(populated_repo, rust_repo_api_client, admin_auth_headers):
    """Yanking the same version twice should be a no-op the second time."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)

    repo_after_first = rust_repo_api_client.read(repo_href)
    first_version = repo_after_first.latest_version_href

    # Yank again — should be no-op
    response = cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    repo_after_second = rust_repo_api_client.read(repo_href)
    assert repo_after_second.latest_version_href == first_version


def test_unyank_idempotent(populated_repo, rust_repo_api_client, admin_auth_headers):
    """Unyanking something not yanked should be a no-op."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    repo_before = rust_repo_api_client.read(repo_href)
    before_version = repo_before.latest_version_href

    response = cargo_unyank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    repo_after = rust_repo_api_client.read(repo_href)
    assert repo_after.latest_version_href == before_version


# --- Multi-repository isolation ---


def test_yank_isolation_across_repositories(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_distro_api_client,
    monitor_task,
    cargo_registry_url,
    admin_auth_headers,
):
    """Yank state is per-repository: yanking/unyanking in one repo must not affect another."""
    remote = rust_remote_factory(url=CRATES_IO_URL)

    # Create two repos, both caching the same crate
    repos = {}
    for label in ("a", "b"):
        repository = rust_repo_factory(remote=remote.pulp_href)
        distribution = rust_distribution_factory(
            remote=remote.pulp_href, repository=repository.pulp_href
        )
        base_url = cargo_registry_url(distribution.base_path)

        # Pull through to cache
        download_file(urljoin(base_url, "api/v1/crates/itoa/1.0.0/download"))

        # Detach remote from distribution so index is served from local content
        monitor_task(
            rust_distro_api_client.partial_update(distribution.pulp_href, {"remote": None}).task
        )

        repos[label] = {"base_url": base_url}

    # Yank in repo A only
    cargo_yank(repos["a"]["base_url"], "itoa", "1.0.0", headers=admin_auth_headers)

    # Repo A should show yanked, repo B should not
    entry_a = get_index_entry(repos["a"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_a["yanked"] is True
    entry_b = get_index_entry(repos["b"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_b["yanked"] is False

    # Yank in repo B too, then unyank only in A
    cargo_yank(repos["b"]["base_url"], "itoa", "1.0.0", headers=admin_auth_headers)
    cargo_unyank(repos["a"]["base_url"], "itoa", "1.0.0", headers=admin_auth_headers)

    # A should be not-yanked, B should remain yanked
    entry_a = get_index_entry(repos["a"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_a["yanked"] is False
    entry_b = get_index_entry(repos["b"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_b["yanked"] is True


# --- Repository versioning ---


def test_yank_creates_new_repo_version(populated_repo, rust_repo_api_client, admin_auth_headers):
    """Yanking should create a new repository version."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    repo_before = rust_repo_api_client.read(repo_href)
    version_before = repo_before.latest_version_href

    cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)

    repo_after = rust_repo_api_client.read(repo_href)
    assert repo_after.latest_version_href != version_before


# --- Partial yank (multiple versions) ---


def test_partial_yank(populated_repo, admin_auth_headers):
    """Yanking one version should not affect other versions of the same crate."""
    base_url = populated_repo["base_url"]

    # Yank only 1.0.0
    cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)

    # 1.0.0 should be yanked
    entry_100 = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry_100["yanked"] is True

    # 1.0.1 should not be yanked
    entry_101 = get_index_entry(base_url, "it/oa/itoa", "1.0.1")
    assert entry_101["yanked"] is False


# --- Download after yank ---


def test_download_still_works_after_yank(populated_repo, admin_auth_headers):
    """Per Cargo spec, yanked crates must remain downloadable."""
    base_url = populated_repo["base_url"]

    # Download before yank to get reference checksum
    download_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/download")
    before = download_file(download_url)
    checksum_before = hashlib.sha256(before.body).hexdigest()

    # Yank
    cargo_yank(base_url, "itoa", "1.0.0", headers=admin_auth_headers)

    # Download should still work
    after = download_file(download_url)
    assert after.response_obj.status == 200
    assert hashlib.sha256(after.body).hexdigest() == checksum_before


# --- Proxy passthrough ---


def test_proxied_index_preserves_upstream_yanked_status(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Proxied index responses should pass through upstream's yanked status verbatim."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )
    base_url = cargo_registry_url(distribution.base_path)

    # serde 0.7.6 is known to be yanked on crates.io
    entries = get_all_index_entries(base_url, "se/rd/serde")

    yanked_entries = [e for e in entries if e["yanked"] is True]
    not_yanked_entries = [e for e in entries if e["yanked"] is False]

    # There should be both yanked and non-yanked versions
    assert len(yanked_entries) > 0, "Expected at least one yanked serde version from upstream"
    assert len(not_yanked_entries) > 0, "Expected at least one non-yanked serde version"
