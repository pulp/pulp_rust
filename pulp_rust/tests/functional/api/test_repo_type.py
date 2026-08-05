"""Tests for repository type enforcement on distributions."""

import pytest

from pulpcore.client.pulp_rust.exceptions import ApiException

from pulp_rust.tests.functional.utils import CRATES_IO_URL


def test_distribution_with_uploads_requires_private_repo(
    rust_repo_factory,
    rust_distribution_factory,
):
    """A distribution with allow_uploads must be linked to a 'private' repo."""
    cache_repo = rust_repo_factory(repo_type="cache")

    with pytest.raises(ApiException) as exc:
        rust_distribution_factory(repository=cache_repo.pulp_href, allow_uploads=True)
    assert exc.value.status == 400


def test_distribution_with_remote_requires_cache_repo(
    rust_repo_factory,
    rust_remote_factory,
    rust_distribution_factory,
):
    """A distribution with a remote must be linked to a 'cache' repo."""
    private_repo = rust_repo_factory(repo_type="private")
    remote = rust_remote_factory(url=CRATES_IO_URL)

    with pytest.raises(ApiException) as exc:
        rust_distribution_factory(repository=private_repo.pulp_href, remote=remote.pulp_href)
    assert exc.value.status == 400


def test_distribution_with_uploads_and_private_repo_succeeds(
    rust_repo_factory,
    rust_distribution_factory,
):
    """A distribution with allow_uploads and a 'private' repo should succeed."""
    repo = rust_repo_factory(repo_type="private")
    distro = rust_distribution_factory(repository=repo.pulp_href, allow_uploads=True)
    assert distro is not None


def test_distribution_with_remote_and_cache_repo_succeeds(
    rust_repo_factory,
    rust_remote_factory,
    rust_distribution_factory,
):
    """A distribution with a remote and a 'cache' repo should succeed."""
    repo = rust_repo_factory(repo_type="cache")
    remote = rust_remote_factory(url=CRATES_IO_URL)
    distro = rust_distribution_factory(repository=repo.pulp_href, remote=remote.pulp_href)
    assert distro is not None


def test_update_distribution_to_wrong_repo_type_rejected(
    rust_repo_factory,
    rust_remote_factory,
    rust_distribution_factory,
    rust_distro_api_client,
    monitor_task,
):
    """Updating a distribution to link a repo with the wrong type should be rejected."""
    cache_repo = rust_repo_factory(repo_type="cache")
    private_repo = rust_repo_factory(repo_type="private")
    remote = rust_remote_factory(url=CRATES_IO_URL)

    # Create a valid cache distribution
    distro = rust_distribution_factory(repository=cache_repo.pulp_href, remote=remote.pulp_href)

    # Try to switch it to a private repo while keeping the remote
    with pytest.raises(ApiException) as exc:
        rust_distro_api_client.partial_update(
            distro.pulp_href, {"repository": private_repo.pulp_href}
        )
    assert exc.value.status == 400
