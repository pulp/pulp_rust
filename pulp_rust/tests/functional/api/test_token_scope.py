"""Tests for Cargo token scoping.

A token may be restricted to a set of distributions and a set of actions. Scopes only
narrow what the owner can already do, so these tests use a user with full permissions and
check that the scopes alone are what blocks the request.
"""

import uuid
from urllib.parse import urljoin

import pytest
import requests

from pulpcore.client.pulp_rust.exceptions import ApiException

from pulp_rust.tests.functional.utils import (
    cargo_unyank,
    cargo_yank,
    minimal_publish_request,
)

# --- Action scopes ---


def test_publish_scoped_token_cannot_yank(
    rust_token_factory,
    pulp_admin_user,
    populated_repo,
):
    """A token scoped to publish should be rejected on yank."""
    token = rust_token_factory(pulp_admin_user, actions=["publish"])
    headers = {"Authorization": token.token}
    base_url = populated_repo["base_url"]

    response = cargo_yank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("not scoped for the yank action" in e["detail"] for e in errors)


def test_yank_scoped_token_cannot_publish(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A token scoped to yank should be rejected on publish."""
    token = rust_token_factory(pulp_admin_user, actions=["yank"])
    headers = {"Authorization": token.token}

    repository = rust_repo_factory()
    distribution = rust_distribution_factory(repository=repository.pulp_href, allow_uploads=True)
    base = cargo_registry_url(distribution.base_path)

    response = minimal_publish_request(base, headers=headers)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("not scoped for the publish action" in e["detail"] for e in errors)


def test_yank_scoped_token_can_yank_and_unyank(
    rust_token_factory,
    pulp_admin_user,
    populated_repo,
):
    """A token scoped to yank should allow both yank and unyank."""
    token = rust_token_factory(pulp_admin_user, actions=["yank"])
    headers = {"Authorization": token.token}
    base_url = populated_repo["base_url"]

    response = cargo_yank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 200

    response = cargo_unyank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 200


def test_unscoped_token_allows_every_action(
    rust_token_factory,
    pulp_admin_user,
    populated_repo,
):
    """A token created without scopes should not be narrowed at all."""
    token = rust_token_factory(pulp_admin_user)
    headers = {"Authorization": token.token}
    base_url = populated_repo["base_url"]

    response = cargo_yank(base_url, "itoa", "1.0.0", headers=headers)
    assert response.status_code == 200


def test_unknown_action_rejected(pulp_api_v3_url, bindings_cfg):
    """Creating a token with an action outside the known set should be rejected.

    Sent as a raw request because the generated client rejects the value locally.
    """
    response = requests.post(
        urljoin(pulp_api_v3_url, "cargo/tokens/"),
        json={"name": str(uuid.uuid4()), "actions": ["delete-everything"]},
        auth=(bindings_cfg.username, bindings_cfg.password),
    )
    assert response.status_code == 400
    assert "actions" in response.json()


# --- Distribution scopes ---


def test_token_rejected_on_unscoped_distribution(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A token scoped to one distribution should be rejected on another."""
    scoped_distribution = rust_distribution_factory(
        repository=rust_repo_factory().pulp_href, allow_uploads=True
    )
    other_distribution = rust_distribution_factory(
        repository=rust_repo_factory().pulp_href, allow_uploads=True
    )

    token = rust_token_factory(pulp_admin_user, distributions=[scoped_distribution.pulp_href])
    headers = {"Authorization": token.token}

    base = cargo_registry_url(other_distribution.base_path)
    response = minimal_publish_request(base, headers=headers)
    assert response.status_code == 403
    errors = response.json()["errors"]
    assert any("not scoped for this distribution" in e["detail"] for e in errors)


def test_token_accepted_on_scoped_distribution(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A token scoped to a distribution should be accepted on that distribution."""
    distribution = rust_distribution_factory(
        repository=rust_repo_factory().pulp_href, allow_uploads=True
    )
    token = rust_token_factory(pulp_admin_user, distributions=[distribution.pulp_href])
    headers = {"Authorization": token.token}

    base = cargo_registry_url(distribution.base_path)
    response = minimal_publish_request(base, headers=headers)
    # The crate payload is fake, so this fails validation rather than scoping.
    assert response.status_code != 403


def test_token_can_be_scoped_to_several_distributions(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    cargo_registry_url,
):
    """A token scoped to several distributions should be accepted on each of them."""
    first = rust_distribution_factory(repository=rust_repo_factory().pulp_href, allow_uploads=True)
    second = rust_distribution_factory(repository=rust_repo_factory().pulp_href, allow_uploads=True)
    token = rust_token_factory(pulp_admin_user, distributions=[first.pulp_href, second.pulp_href])
    headers = {"Authorization": token.token}

    for distribution in (first, second):
        response = minimal_publish_request(
            cargo_registry_url(distribution.base_path), headers=headers
        )
        # The crate payload is fake, so this fails validation rather than scoping.
        assert response.status_code != 403


def test_token_is_revoked_when_its_last_distribution_is_deleted(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
    rust_distro_api_client,
    cargo_registry_url,
    monitor_task,
):
    """Losing the last scoped distribution should revoke the token rather than widen it."""
    first, second, other = (
        rust_distribution_factory(repository=rust_repo_factory().pulp_href, allow_uploads=True)
        for _ in range(3)
    )
    token = rust_token_factory(pulp_admin_user, distributions=[first.pulp_href, second.pulp_href])
    headers = {"Authorization": token.token}

    monitor_task(rust_distro_api_client.delete(first.pulp_href).task)

    # Part of the scope survives, so the token is still narrowed to it.
    kept = minimal_publish_request(cargo_registry_url(second.base_path), headers=headers)
    assert kept.status_code != 403
    rejected = minimal_publish_request(cargo_registry_url(other.base_path), headers=headers)
    assert rejected.status_code == 403

    monitor_task(rust_distro_api_client.delete(second.pulp_href).task)

    # The scope is empty now, so the token is gone instead of applying to everything.
    revoked = minimal_publish_request(cargo_registry_url(other.base_path), headers=headers)
    assert revoked.status_code == 401


def test_scopes_are_readable_on_the_token(
    rust_token_factory,
    pulp_admin_user,
    rust_repo_factory,
    rust_distribution_factory,
):
    """Scopes set at creation should come back on the token."""
    distribution = rust_distribution_factory(repository=rust_repo_factory().pulp_href)
    token = rust_token_factory(
        pulp_admin_user, distributions=[distribution.pulp_href], actions=["publish"]
    )

    assert token.distributions == [distribution.pulp_href]
    assert token.actions == ["publish"]


# --- Scopes narrow, they never grant ---


def test_scoped_token_still_needs_permission(
    gen_user,
    rust_token_factory,
    rust_repo_factory,
    rust_distro_api_client,
    rust_distribution_factory,
    cargo_registry_url,
):
    """Scoping a token to a distribution must not grant access the user lacks."""
    alice = gen_user()
    distribution = rust_distribution_factory(
        repository=rust_repo_factory().pulp_href, allow_uploads=True
    )
    rust_distro_api_client.add_role(
        distribution.pulp_href,
        {"role": "rust.rustdistribution_viewer", "users": [alice.username]},
    )
    token = rust_token_factory(alice, distributions=[distribution.pulp_href])

    # Alice can see the distribution, but seeing it is not permission to publish to it.
    base = cargo_registry_url(distribution.base_path)
    response = minimal_publish_request(base, headers={"Authorization": token.token})
    assert response.status_code == 403


def test_cannot_scope_to_an_invisible_distribution(
    gen_user,
    rust_token_factory,
    rust_repo_factory,
    rust_distribution_factory,
):
    """A distribution the user cannot see should not be selectable as a scope."""
    alice = gen_user()
    distribution = rust_distribution_factory(repository=rust_repo_factory().pulp_href)

    with pytest.raises(ApiException) as exc:
        rust_token_factory(alice, distributions=[distribution.pulp_href])

    assert exc.value.status == 403
