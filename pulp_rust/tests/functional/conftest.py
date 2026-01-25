import uuid

import pytest

from pulpcore.client.pulp_rust import (
    ApiClient,
    ContentArtifactApi,
    DistributionsRustApi,
    RemotesRustApi,
    RepositoriesRustApi,
)


@pytest.fixture(scope="session")
def rust_client(_api_client_set, bindings_cfg):
    api_client = ApiClient(bindings_cfg)
    _api_client_set.add(api_client)
    yield api_client
    _api_client_set.remove(api_client)


@pytest.fixture(scope="session")
def rust_artifact_api_client(rust_client):
    return ContentArtifactApi(rust_client)


@pytest.fixture(scope="session")
def rust_distro_api_client(rust_client):
    return DistributionsRustApi(rust_client)


@pytest.fixture(scope="session")
def rust_repo_api_client(rust_client):
    return RepositoriesRustApi(rust_client)


@pytest.fixture(scope="session")
def rust_remote_api_client(rust_client):
    return RemotesRustApi(rust_client)


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
