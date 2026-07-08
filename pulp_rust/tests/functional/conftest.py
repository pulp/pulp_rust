import uuid
from urllib.parse import urljoin

import pytest

from pulpcore.client.pulp_rust import (
    ApiClient,
    CargoTokensApi,
    ContentPackagesApi,
    DistributionsRustApi,
    RemotesRustApi,
    RepositoriesRustApi,
)
from pulpcore.client.pulp_rust.exceptions import ApiException

from pulp_rust.tests.functional.utils import (
    CRATES_IO_URL,
    download_file,
    get_index_entry,
)


@pytest.fixture(scope="session")
def rust_client(_api_client_set, bindings_cfg):
    api_client = ApiClient(bindings_cfg)
    _api_client_set.add(api_client)
    yield api_client
    _api_client_set.remove(api_client)


@pytest.fixture(scope="session")
def rust_content_api_client(rust_client):
    return ContentPackagesApi(rust_client)


@pytest.fixture(scope="session")
def rust_distro_api_client(rust_client):
    return DistributionsRustApi(rust_client)


@pytest.fixture(scope="session")
def rust_repo_api_client(rust_client):
    return RepositoriesRustApi(rust_client)


@pytest.fixture(scope="session")
def rust_remote_api_client(rust_client):
    return RemotesRustApi(rust_client)


@pytest.fixture(scope="session")
def rust_token_api_client(rust_client):
    return CargoTokensApi(rust_client)


@pytest.fixture
def rust_token_factory(rust_token_api_client, add_to_cleanup):
    def _rust_token_factory(user, **kwargs):
        kwargs.setdefault("name", str(uuid.uuid4()))
        with user:
            token_response = rust_token_api_client.create(kwargs)
        add_to_cleanup(rust_token_api_client, token_response.pulp_href)
        return token_response

    return _rust_token_factory


@pytest.fixture
def rust_distribution_factory(rust_distro_api_client, gen_object_with_cleanup):
    def _rust_distribution_factory(**kwargs):
        data = {"base_path": str(uuid.uuid4()), "name": str(uuid.uuid4())}
        data.update(kwargs)
        return gen_object_with_cleanup(rust_distro_api_client, data)

    return _rust_distribution_factory


@pytest.fixture
def rust_repo_factory(rust_repo_api_client, gen_object_with_cleanup):
    """A factory to generate a Rust Repository with auto-deletion after the test run."""

    def _rust_repo_factory(**kwargs):
        kwargs.setdefault("name", str(uuid.uuid4()))
        return gen_object_with_cleanup(rust_repo_api_client, kwargs)

    yield _rust_repo_factory


@pytest.fixture
def rust_remote_factory(rust_remote_api_client, gen_object_with_cleanup):
    """A factory to generate a Rust Remote with auto-deletion after the test run."""

    def _rust_remote_factory(**kwargs):
        kwargs.setdefault("name", str(uuid.uuid4()))
        return gen_object_with_cleanup(rust_remote_api_client, kwargs)

    yield _rust_remote_factory


@pytest.fixture(scope="session")
def cargo_registry_url(bindings_cfg, pulp_settings):
    """Build the Cargo API base URL for a distribution's base_path.

    The Cargo API views (config.json, sparse index, downloads) are served at
    /pulp/cargo/{base_path}/, not through the content app.
    Accounts for DOMAIN_ENABLED mode which adds a domain slug to the path.
    """

    def _cargo_registry_url(base_path):
        if pulp_settings.DOMAIN_ENABLED:
            return f"{bindings_cfg.host}/pulp/cargo/default/{base_path}/"
        return f"{bindings_cfg.host}/pulp/cargo/{base_path}/"

    return _cargo_registry_url


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
    """Create a repo with itoa 1.0.0 and 1.0.1 pulled-through via on_demand.

    Content is automatically added to the repository during pull-through
    (PULL_THROUGH_SUPPORTED = True). The remote is then detached from the
    distribution so the index is served from local content only.

    Returns a dict with 'repository', 'distribution', 'remote', and 'base_url'.
    """
    remote = rust_remote_factory(url=CRATES_IO_URL)
    repository = rust_repo_factory(remote=remote.pulp_href)
    distribution = rust_distribution_factory(
        remote=remote.pulp_href, repository=repository.pulp_href
    )
    base_url = cargo_registry_url(distribution.base_path)

    # Pull through two versions — each download automatically creates a new
    # repo version with the content added (via PULL_THROUGH_SUPPORTED).
    for version in ("1.0.0", "1.0.1"):
        unit_path = f"api/v1/crates/itoa/{version}/download"
        download_file(urljoin(base_url, unit_path))

    # Detach remote from the distribution so the index is served from local
    # content only (the distribution's remote controls the proxy fallback).
    monitor_task(
        rust_distro_api_client.partial_update(distribution.pulp_href, {"remote": None}).task
    )

    return {
        "repository": rust_repo_api_client.read(repository.pulp_href),
        "distribution": rust_distro_api_client.read(distribution.pulp_href),
        "remote": remote,
        "base_url": base_url,
    }


@pytest.fixture(scope="module")
def upstream_index_entry():
    """Fetch the canonical index entry for serde 1.0.210 from crates.io (once per module)."""
    return get_index_entry("https://index.crates.io/", "se/rd/serde", "1.0.210")


@pytest.fixture
def gen_users(gen_user):
    """Create three users with viewer, creator, and no roles for the given resources."""

    def _gen_users(role_names=None):
        if role_names is None:
            role_names = []
        if isinstance(role_names, str):
            role_names = [role_names]
        viewer_roles = [f"rust.{role}_viewer" for role in role_names]
        creator_roles = [f"rust.{role}_creator" for role in role_names]
        alice = gen_user(model_roles=viewer_roles)
        bob = gen_user(model_roles=creator_roles)
        charlie = gen_user()
        return alice, bob, charlie

    return _gen_users


@pytest.fixture
def try_action(monitor_task):
    """Attempt an API action as a given user and assert the expected HTTP status."""

    def _try_action(user, api_client, action, expected_status, *args, **kwargs):
        action_api = getattr(api_client, f"{action}_with_http_info")
        try:
            with user:
                response = action_api(*args, **kwargs)
            data = response.data
            status_code = response.status_code
            if hasattr(data, "task") and data.task:
                data = monitor_task(data.task)
        except ApiException as e:
            assert e.status == expected_status, f"Expected {expected_status}, got {e.status}: {e}"
        else:
            assert status_code == expected_status, (
                f"Expected {expected_status}, got {status_code} for {action}"
            )
            return data

    return _try_action
