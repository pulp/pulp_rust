"""Tests for stub authentication on Cargo API endpoints."""

from urllib.parse import urljoin

from pulp_rust.tests.functional.utils import (
    CARGO_AUTH_HEADERS,
    cargo_api_request,
    download_file,
    get_index_entry,
    minimal_publish_request,
)

# --- 403 tests for missing/wrong token ---


def test_publish_without_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publish without an Authorization header should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = minimal_publish_request(base)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("authorization token" in e["detail"] for e in errors)


def test_publish_with_wrong_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publish with an incorrect token should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = minimal_publish_request(base, headers={"Authorization": "wrong-token"})
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("invalid" in e["detail"] for e in errors)


def test_yank_without_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Yank without an Authorization header should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    yank_url = urljoin(base, "api/v1/crates/fake/0.0.1/yank")
    response = cargo_api_request("DELETE", yank_url)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("authorization token" in e["detail"] for e in errors)


def test_unyank_without_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Unyank without an Authorization header should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    unyank_url = urljoin(base, "api/v1/crates/fake/0.0.1/unyank")
    response = cargo_api_request("PUT", unyank_url)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("authorization token" in e["detail"] for e in errors)


# --- /me endpoint (cargo login verification) ---


def test_me_with_valid_token(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """/me with a valid token should return 200 {"ok": true}."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_api_request("GET", urljoin(base, "me"), headers=CARGO_AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_me_without_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """/me without a token should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_api_request("GET", urljoin(base, "me"))
    assert response.status_code == 403


def test_me_with_wrong_token_returns_403(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """/me with an invalid token should return 403."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_api_request("GET", urljoin(base, "me"), headers={"Authorization": "wrong"})
    assert response.status_code == 403


# --- Public endpoints remain accessible without token ---


def test_download_without_token_succeeds(populated_repo):
    """Downloads should work without any authorization token."""
    base_url = populated_repo["base_url"]
    download_url = urljoin(base_url, "api/v1/crates/itoa/1.0.0/download")
    result = download_file(download_url)
    assert result.response_obj.status == 200


def test_index_without_token_succeeds(populated_repo):
    """The sparse index should be accessible without any authorization token."""
    base_url = populated_repo["base_url"]
    entry = get_index_entry(base_url, "it/oa/itoa", "1.0.0")
    assert entry is not None
    assert entry["name"] == "itoa"
