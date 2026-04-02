"""Tests for uploading crate content via the Pulp REST API and verifying index fidelity."""

from pulpcore.client.pulp_rust import RustRustContent, RustDependency

from pulp_rust.tests.functional.utils import (
    assert_index_entry_matches_upstream,
    download_crate_from_upstream,
    get_index_entry,
)
from pulp_rust.app.utils import extract_cargo_toml, extract_dependencies


def test_upload_and_index_fidelity(
    delete_orphans_pre,
    rust_repo_factory,
    rust_distribution_factory,
    rust_content_api_client,
    rust_repo_api_client,
    monitor_task,
    cargo_registry_url,
    pulpcore_bindings,
    upstream_index_entry,
):
    """Upload a crate via the REST API and verify the index matches crates.io."""
    crate_name = "serde"
    crate_version = "1.0.210"

    # 1. Download .crate directly from crates.io
    crate_path, cksum = download_crate_from_upstream(crate_name, crate_version)

    # 2. Parse metadata from the .crate file
    cargo_toml = extract_cargo_toml(crate_path, crate_name, crate_version)
    deps = extract_dependencies(cargo_toml)
    features = cargo_toml.get("features", {})
    links = cargo_toml.get("package", {}).get("links")
    rust_version = cargo_toml.get("package", {}).get("rust-version")

    # 3. Upload the .crate as an artifact
    artifact = pulpcore_bindings.ArtifactsApi.create(crate_path)

    # 4. Create the RustContent with metadata
    content = rust_content_api_client.create(
        RustRustContent(
            artifact=artifact.pulp_href,
            relative_path=f"{crate_name}/{crate_name}-{crate_version}.crate",
            name=crate_name,
            vers=crate_version,
            cksum=cksum,
            dependencies=[
                RustDependency(
                    name=dep["name"],
                    req=dep["req"],
                    features=dep["features"],
                    optional=dep["optional"],
                    default_features=dep["default_features"],
                    target=dep["target"],
                    kind=dep["kind"],
                    registry=dep.get("registry"),
                    package=dep.get("package"),
                )
                for dep in deps
            ],
            features=features,
            links=links,
            rust_version=rust_version,
        )
    )

    # 5. Create a repository and add the content
    repository = rust_repo_factory()
    monitor_task(
        rust_repo_api_client.modify(
            repository.pulp_href,
            {"add_content_units": [content.pulp_href]},
        ).task
    )

    # 6. Create a distribution (no remote — purely local)
    distribution = rust_distribution_factory(repository=repository.pulp_href)
    base = cargo_registry_url(distribution.base_path)

    # 7. Fetch the index from Pulp and compare against crates.io
    pulp_entry = get_index_entry(base, "se/rd/serde", "1.0.210")
    assert_index_entry_matches_upstream(pulp_entry, upstream_index_entry)
