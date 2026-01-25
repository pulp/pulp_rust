"""Tests that verify download of content served by Pulp."""

from aiohttp.client_exceptions import ClientResponseError
import hashlib
from urllib.parse import urljoin

from pulp_rust.tests.functional.utils import download_file


def test_download_content(
    rust_distribution_factory,
    rust_remote_factory,
    rust_repo_factory,
    rust_artifact_api_client,
    rust_distro_api_client,
    rust_repo_api_client,
    monitor_task,
    distribution_base_url,
):
    """Verify whether content served by pulp can be downloaded.

    The process of creating a Cargo mirror is:

    1. Create a Rust Remote with a URL pointing to the root of a Cargo repository.
    2. Create a distribution with the remote set HREF from 1.

    Do the following:

    1. Create a Rust Remote and a Distribution.
    2. Select a random content unit in the distribution. Download that
       content unit from Pulp, and verify that the content unit has the
       same checksum when fetched directly from Cargo.
    """
    remote = rust_remote_factory(url="sparse+https://index.crates.io/")
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # Pick a content unit, and download it from the remote repository
    unit_path = "api/v1/crates/ripgrep/15.1.0/download"
    remote_unit_url = urljoin(remote.url, unit_path)
    downloaded_file = download_file(remote_unit_url)
    remote_unit_checksum = hashlib.sha256(downloaded_file.body).hexdigest()

    # And from Pulp
    pulp_unit_url = urljoin(distribution_base_url(distribution.base_url), unit_path)
    downloaded_file = download_file(pulp_unit_url)
    pulp_unit_checksum = hashlib.sha256(downloaded_file.body).hexdigest()

    assert remote_unit_checksum == pulp_unit_checksum

    # Check that Pulp created a Rust artifact
    content_response = rust_artifact_api_client.list()  # todo: filter for better idempotence
    assert content_response.count == 1

    # Remove the remote from the distribution
    monitor_task(
        rust_distro_api_client.partial_update(distribution.pulp_href, {"remote": None}).task
    )

    # Assert that the rust artifact is no longer available
    try:
        download_file(pulp_unit_url)
    except ClientResponseError as e:
        assert e.status == 404

    # Assert that the repository version is 0
    assert repository.latest_version_href.endswith("/versions/0/")

    # Add cached content to the repository
    monitor_task(rust_repo_api_client.add_cached_content(repository.pulp_href, {}).task)

    # Assert that the repository is at version 1
    repository = rust_repo_api_client.read(repository.pulp_href)
    assert repository.latest_version_href.endswith("/versions/1/")

    # Assert that it is now once again available from the same distribution
    downloaded_file = download_file(pulp_unit_url)
    assert downloaded_file.response_obj.status == 200
