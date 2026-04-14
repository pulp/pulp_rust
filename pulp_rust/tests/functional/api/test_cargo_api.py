"""Functional tests for the Cargo registry API endpoints."""

import json
import uuid
from urllib.parse import urljoin

import pytest
from aiohttp.client_exceptions import ClientResponseError
from pulpcore.client.pulp_rust.exceptions import ApiException

from pulp_rust.tests.functional.utils import CRATES_IO_URL, download_file


def test_config_json(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """config.json should return dl and api URLs pointing at Pulp."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)

    config_url = urljoin(cargo_registry_url(distribution.base_path), "config.json")
    downloaded = download_file(config_url)
    assert downloaded.response_obj.status == 200

    config = json.loads(downloaded.body)
    assert "dl" in config
    assert "api" in config
    assert "auth-required" in config
    assert "/api/v1/crates" in config["dl"]


def test_config_json_accept_text_plain(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """config.json should be served when Accept: text/plain is sent (as Cargo does)."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)

    config_url = urljoin(cargo_registry_url(distribution.base_path), "config.json")
    downloaded = download_file(config_url, headers={"Accept": "text/plain"})
    assert downloaded.response_obj.status == 200

    config = json.loads(downloaded.body)
    assert "dl" in config


def test_config_json_dl_points_to_pulp(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """The dl URL in config.json should point at Pulp, not upstream."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    config_url = urljoin(cargo_registry_url(distribution.base_path), "config.json")
    downloaded = download_file(config_url)
    config = json.loads(downloaded.body)

    assert "crates.io" not in config["dl"]


def test_sparse_index_nonexistent_crate_no_remote(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Without a remote, requesting a nonexistent crate should 404."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)

    index_url = urljoin(cargo_registry_url(distribution.base_path), "zz/zz/zzzznotacrate")
    with pytest.raises(ClientResponseError) as exc:
        download_file(index_url)
    assert exc.value.status == 404


def test_sparse_index_proxy_valid_ndjson(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Proxied sparse index response should be valid newline-delimited JSON."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # "itoa" (4 chars) -> sparse path "it/oa/itoa"
    index_url = urljoin(cargo_registry_url(distribution.base_path), "it/oa/itoa")
    downloaded = download_file(index_url)
    assert downloaded.response_obj.status == 200

    body = downloaded.body.decode("utf-8")
    lines = body.strip().split("\n")
    assert len(lines) > 0

    for line in lines:
        entry = json.loads(line)
        assert entry["name"] == "itoa"
        assert "vers" in entry
        assert "cksum" in entry
        assert "deps" in entry


def test_sparse_index_proxy_matches_upstream(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Proxied sparse index response should match what crates.io returns directly."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # Fetch from crates.io directly
    upstream = download_file("https://index.crates.io/it/oa/itoa")
    # Fetch through Pulp
    pulp_url = urljoin(cargo_registry_url(distribution.base_path), "it/oa/itoa")
    proxied = download_file(pulp_url)

    assert upstream.body == proxied.body


def test_sparse_index_proxy_nonexistent_crate(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Even with a remote, a nonexistent crate should 404."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    index_url = urljoin(cargo_registry_url(distribution.base_path), "zz/zz/zzzznotacrate")
    with pytest.raises(ClientResponseError) as exc:
        download_file(index_url)
    assert exc.value.status == 404


def test_sparse_index_proxy_crate_with_dependencies(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Proxied metadata for a crate with dependencies should include dep data."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    # "serde" has dependencies (serde_derive) in some versions
    index_url = urljoin(cargo_registry_url(distribution.base_path), "se/rd/serde")
    downloaded = download_file(index_url)
    assert downloaded.response_obj.status == 200

    body = downloaded.body.decode("utf-8")
    lines = body.strip().split("\n")
    assert len(lines) > 10

    has_deps = any(len(json.loads(line).get("deps", [])) > 0 for line in lines)
    assert has_deps


def test_sparse_index_proxy_single_char_crate(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Sparse index path for single-char crate: 1/{name}."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    index_url = urljoin(cargo_registry_url(distribution.base_path), "1/q")
    downloaded = download_file(index_url)
    assert downloaded.response_obj.status == 200


def test_sparse_index_proxy_three_char_crate(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Sparse index path for three-char crate: 3/{first-char}/{name}."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )

    index_url = urljoin(cargo_registry_url(distribution.base_path), "3/l/log")
    downloaded = download_file(index_url)
    assert downloaded.response_obj.status == 200


def test_distribution_detach_remote(
    rust_remote_factory,
    rust_repo_factory,
    rust_distribution_factory,
    rust_distro_api_client,
    monitor_task,
):
    """A remote can be attached and detached from a distribution."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repo = rust_repo_factory()
    distro = rust_distribution_factory(remote=remote.pulp_href, repository=repo.pulp_href)

    distro = rust_distro_api_client.read(distro.pulp_href)
    assert distro.remote == remote.pulp_href

    monitor_task(rust_distro_api_client.partial_update(distro.pulp_href, {"remote": None}).task)
    distro = rust_distro_api_client.read(distro.pulp_href)
    assert distro.remote is None


def test_add_cached_content_empty_repo(
    rust_remote_factory,
    rust_repo_factory,
    rust_repo_api_client,
    monitor_task,
):
    """add_cached_content on a repo with no cached content creates a new version."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)

    monitor_task(
        rust_repo_api_client.add_cached_content(
            repository.pulp_href, {"remote": remote.pulp_href}
        ).task
    )

    repository = rust_repo_api_client.read(repository.pulp_href)
    assert repository.latest_version_href is not None


def test_distribution_rejects_remote_with_uploads(
    rust_remote_factory,
    rust_repo_factory,
    rust_distro_api_client,
):
    """Creating a distribution with both a remote and allow_uploads should fail."""
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repo = rust_repo_factory()

    with pytest.raises(ApiException) as exc:
        rust_distro_api_client.create(
            {
                "name": str(uuid.uuid4()),
                "base_path": str(uuid.uuid4()),
                "repository": repo.pulp_href,
                "remote": remote.pulp_href,
                "allow_uploads": True,
            }
        )
    assert exc.value.status == 400


def test_distribution_update_rejects_remote_with_uploads(
    rust_repo_factory,
    rust_distribution_factory,
    rust_remote_factory,
    rust_distro_api_client,
):
    """Updating a distribution to set both remote and allow_uploads should fail."""
    repo = rust_repo_factory()
    distro = rust_distribution_factory(repository=repo.pulp_href)
    remote = rust_remote_factory(url=CRATES_IO_URL)

    with pytest.raises(ApiException) as exc:
        rust_distro_api_client.partial_update(
            distro.pulp_href, {"remote": remote.pulp_href, "allow_uploads": True}
        )
    assert exc.value.status == 400
