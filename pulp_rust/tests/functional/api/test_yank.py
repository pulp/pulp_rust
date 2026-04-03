"""Functional tests for Cargo yank/unyank support."""

import hashlib
import json
from urllib.parse import urljoin

import pytest
from requests.exceptions import HTTPError

from pulp_rust.tests.functional.utils import (
    CARGO_AUTH_HEADERS,
    CRATES_IO_URL,
    cargo_api_request,
    download_file,
    get_index_entry,
)


def cargo_yank_request(url, method="DELETE"):
    """Make an authenticated DELETE or PUT request to the Cargo yank/unyank API."""
    response = cargo_api_request(method, url, headers=CARGO_AUTH_HEADERS)
    response.raise_for_status()
    return response.json()


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


def test_yank_happy_path(populated_repo):
    """Yanking a crate version via the Cargo API should mark it as yanked in the index."""
    base_url = populated_repo["base_url"]

    # Verify initially not yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry is not None
    assert entry["yanked"] is False

    # Yank via Cargo API
    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    result = cargo_yank_request(yank_url, method="DELETE")
    assert result["ok"] is True

    # Verify now yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is True


def test_unyank_happy_path(populated_repo):
    """Unyanking a crate version should restore it in the index."""
    base_url = populated_repo["base_url"]

    # Yank first
    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is True

    # Unyank
    unyank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/unyank")
    result = cargo_yank_request(unyank_url, method="PUT")
    assert result["ok"] is True

    # Verify no longer yanked
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry["yanked"] is False


# --- Error cases ---


def test_yank_nonexistent_package(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Yanking a crate that doesn't exist in the repo should fail."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base_url = cargo_registry_url(distribution.base_path)

    yank_url = urljoin(base_url, "api/v1/crates/nonexistent/0.0.0/yank")
    with pytest.raises(HTTPError) as exc:
        cargo_yank_request(yank_url, method="DELETE")
    assert exc.value.response.status_code == 404


def test_yank_no_repository(
    rust_distribution_factory,
    cargo_registry_url,
):
    """Yanking on a distribution with no repository should 404."""
    distribution = rust_distribution_factory()
    base_url = cargo_registry_url(distribution.base_path)

    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    with pytest.raises(HTTPError) as exc:
        cargo_yank_request(yank_url, method="DELETE")
    assert exc.value.response.status_code == 404


# --- Idempotency ---


def test_yank_idempotent(populated_repo, rust_repo_api_client):
    """Yanking the same version twice should be a no-op the second time."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

    repo_after_first = rust_repo_api_client.read(repo_href)
    first_version = repo_after_first.latest_version_href

    # Yank again — should be no-op
    result = cargo_yank_request(yank_url, method="DELETE")
    assert result["ok"] is True

    repo_after_second = rust_repo_api_client.read(repo_href)
    assert repo_after_second.latest_version_href == first_version


def test_unyank_idempotent(populated_repo, rust_repo_api_client):
    """Unyanking something not yanked should be a no-op."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    repo_before = rust_repo_api_client.read(repo_href)
    before_version = repo_before.latest_version_href

    unyank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/unyank")
    result = cargo_yank_request(unyank_url, method="PUT")
    assert result["ok"] is True

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
    yank_url = urljoin(repos["a"]["base_url"], "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

    # Repo A should show yanked, repo B should not
    entry_a = get_index_entry(repos["a"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_a["yanked"] is True
    entry_b = get_index_entry(repos["b"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_b["yanked"] is False

    # Yank in repo B too, then unyank only in A
    yank_url_b = urljoin(repos["b"]["base_url"], "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url_b, method="DELETE")

    unyank_url = urljoin(repos["a"]["base_url"], "api/v1/crates/itoa/1.0.0/unyank")
    cargo_yank_request(unyank_url, method="PUT")

    # A should be not-yanked, B should remain yanked
    entry_a = get_index_entry(repos["a"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_a["yanked"] is False
    entry_b = get_index_entry(repos["b"]["base_url"], "it/oa/itoa", "1.0.0")
    assert entry_b["yanked"] is True


# --- Repository versioning ---


def test_yank_creates_new_repo_version(populated_repo, rust_repo_api_client):
    """Yanking should create a new repository version."""
    base_url = populated_repo["base_url"]
    repo_href = populated_repo["repository"].pulp_href

    repo_before = rust_repo_api_client.read(repo_href)
    version_before = repo_before.latest_version_href

    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

    repo_after = rust_repo_api_client.read(repo_href)
    assert repo_after.latest_version_href != version_before


# --- Partial yank (multiple versions) ---


def test_partial_yank(populated_repo):
    """Yanking one version should not affect other versions of the same crate."""
    base_url = populated_repo["base_url"]

    # Yank only 1.0.0
    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

    # 1.0.0 should be yanked
    entry_100 = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry_100["yanked"] is True

    # 1.0.1 should not be yanked
    entry_101 = get_index_entry(base_url, "it/oa/itoa", "1.0.1")
    assert entry_101["yanked"] is False


# --- Download after yank ---


def test_download_still_works_after_yank(populated_repo):
    """Per Cargo spec, yanked crates must remain downloadable."""
    base_url = populated_repo["base_url"]

    # Download before yank to get reference checksum
    download_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/download")
    before = download_file(download_url)
    checksum_before = hashlib.sha256(before.body).hexdigest()

    # Yank
    yank_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/yank")
    cargo_yank_request(yank_url, method="DELETE")

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
