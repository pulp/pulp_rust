"""Tests for Cargo token authentication on Cargo API endpoints."""

from urllib.parse import urljoin

from pulp_rust.tests.functional.utils import (
    cargo_api_request,
    cargo_unyank,
    cargo_yank,
    download_file,
    get_index_entry,
    minimal_publish_request,
)

# --- Unauthenticated requests ---


def test_publish_without_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publish without an Authorization header should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = minimal_publish_request(base)
    assert response.status_code == 401


def test_yank_without_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Yank without an Authorization header should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_yank(base, "fake", "0.0.1")
    assert response.status_code == 401


def test_unyank_without_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Unyank without an Authorization header should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_unyank(base, "fake", "0.0.1")
    assert response.status_code == 401


# --- Invalid token ---


def test_publish_with_wrong_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Publish with an invalid crg_ token should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = minimal_publish_request(base, headers={"Authorization": "crg_wrongtoken"})
    assert response.status_code == 401


def test_me_with_wrong_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """/me with an invalid crg_ token should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_api_request("GET", urljoin(base, "me"), headers={"Authorization": "crg_wrong"})
    assert response.status_code == 401


# --- Valid token ---


def test_me_with_valid_token(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
    rust_token_factory,
    pulp_admin_user,
):
    """/me with a valid token should return 200 {"ok": true}."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)
    token = rust_token_factory(pulp_admin_user)

    response = cargo_api_request("GET", urljoin(base, "me"), headers={"Authorization": token.token})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_me_without_token_returns_401(
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """/me without a token should return 401."""
    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    response = cargo_api_request("GET", urljoin(base, "me"))
    assert response.status_code == 401


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


# --- Token lifecycle ---


def test_token_list_only_shows_own_tokens(gen_user, rust_token_factory, rust_token_api_client):
    """Users should only see their own tokens, not other users' tokens."""
    alice = gen_user()
    bob = gen_user()

    rust_token_factory(alice, name="alice-token")
    rust_token_factory(bob, name="bob-token")

    with alice:
        alice_tokens = rust_token_api_client.list()
        names = [t.name for t in alice_tokens.results]
        assert "alice-token" in names
        assert "bob-token" not in names


def test_revoked_token_returns_401(
    rust_token_factory,
    rust_token_api_client,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A deleted token should no longer authenticate."""
    token = rust_token_factory(pulp_admin_user)
    headers = {"Authorization": token.token}

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    # Works before revocation
    response = cargo_api_request("GET", urljoin(base, "me"), headers=headers)
    assert response.status_code == 200

    # Revoke
    rust_token_api_client.delete(token.pulp_href)

    # Fails after revocation
    response = cargo_api_request("GET", urljoin(base, "me"), headers=headers)
    assert response.status_code == 401


def test_token_not_returned_on_list(
    rust_token_factory,
    rust_token_api_client,
    pulp_admin_user,
):
    """The raw token value should not be visible when listing tokens."""
    rust_token_factory(pulp_admin_user)

    tokens = rust_token_api_client.list()
    assert tokens.count >= 1
    for t in tokens.results:
        assert t.token is None


# --- Distribution-scoped permissions ---


def test_publish_requires_distribution_permission(
    gen_user,
    rust_token_factory,
    rust_repo_factory,
    rust_distro_api_client,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A user without publish permission on the distribution should get 403."""
    alice = gen_user()
    token = rust_token_factory(alice)
    headers = {"Authorization": token.token}

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    # Alice has no publish permission — should get 403
    response = minimal_publish_request(base, headers=headers)
    assert response.status_code == 403

    # Grant publisher role on the distribution
    rust_distro_api_client.add_role(
        distribution.pulp_href,
        {"role": "rust.rustdistribution_publisher", "users": [alice.username]},
    )

    # Now Alice can publish
    response = minimal_publish_request(base, headers=headers)
    # Won't be 403 anymore — might be 400 (fake crate) but not a permission error
    assert response.status_code != 403


def test_yank_requires_distribution_permission(
    gen_user,
    rust_token_factory,
    rust_repo_factory,
    rust_distro_api_client,
    rust_distribution_factory,
    cargo_registry_url,
    populated_repo,
):
    """A user without yank permission on the distribution should get 403."""
    alice = gen_user()
    token = rust_token_factory(alice)
    headers = {"Authorization": token.token}

    base_url = populated_repo["base_url"]
    distro_href = populated_repo["distribution"].pulp_href

    # Alice has no yank permission — should get 403
    response = cargo_yank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 403

    # Grant publisher role (includes yank)
    rust_distro_api_client.add_role(
        distro_href,
        {"role": "rust.rustdistribution_publisher", "users": [alice.username]},
    )

    # Now Alice can yank
    response = cargo_yank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 200
