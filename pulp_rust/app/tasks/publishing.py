import hashlib
import struct

from pulpcore.plugin.models import Artifact, ContentArtifact
from pulpcore.plugin.tasking import aadd_and_remove

from pulp_rust.app.models import RustContent, RustDependency, RustRepository
from pulp_rust.app.utils import extract_cargo_toml, extract_dependencies


def parse_cargo_publish_body(body):
    """
    Parse the binary request body from ``cargo publish``.

    Format (per https://doc.rust-lang.org/cargo/reference/registry-web-api.html#publish):
        4 bytes: JSON metadata length (little-endian u32)
        N bytes: JSON metadata (UTF-8)
        4 bytes: .crate file length (little-endian u32)
        M bytes: .crate file (binary)

    Returns:
        (metadata_dict, crate_bytes)
    """
    import json

    offset = 0

    json_len = struct.unpack_from("<I", body, offset)[0]
    offset += 4

    json_bytes = body[offset : offset + json_len]
    offset += json_len
    metadata = json.loads(json_bytes)

    crate_len = struct.unpack_from("<I", body, offset)[0]
    offset += 4

    crate_bytes = body[offset : offset + crate_len]
    offset += crate_len

    return metadata, crate_bytes


async def apublish_package(repository_pk, metadata, crate_path):
    """
    Publish a crate to a repository.

    Creates the Artifact, RustContent, ContentArtifact, and RustDependency records,
    then adds the content to a new repository version.

    Args:
        repository_pk: Primary key of the target repository.
        metadata: Parsed JSON metadata from the cargo publish request.
        crate_path: Filesystem path to the .crate tarball.
    """
    repository = await RustRepository.objects.aget(pk=repository_pk)

    # Create the artifact from the .crate file
    with open(crate_path, "rb") as f:
        cksum = hashlib.sha256(f.read()).hexdigest()

    artifact = Artifact.init_and_validate(crate_path, expected_digests={"sha256": cksum})
    await artifact.asave()

    # Extract authoritative metadata from the Cargo.toml inside the .crate tarball.
    # The publish JSON metadata is NOT authoritative — a rogue client can send metadata
    # that doesn't match the actual package. We only use the JSON name/vers to locate the
    # Cargo.toml within the tarball, then extract everything from the Cargo.toml itself.
    # See: https://github.com/rust-lang/cargo/issues/14492
    #      https://github.com/rust-lang/crates.io/pull/7238
    cargo_toml = extract_cargo_toml(artifact.file.path, metadata["name"], metadata["vers"])
    package = cargo_toml.get("package", {})

    name = package["name"]
    vers = package["version"]

    # Build dependency list from the Cargo.toml (authoritative source)
    deps = extract_dependencies(cargo_toml)

    # Create the content record
    content = RustContent(
        name=name,
        vers=vers,
        cksum=cksum,
        features=cargo_toml.get("features", {}),
        features2=None,
        links=package.get("links"),
        rust_version=package.get("rust-version"),
        _pulp_domain_id=repository.pulp_domain_id,
    )
    await content.asave()

    # Create dependencies
    if deps:
        await RustDependency.objects.abulk_create(
            [RustDependency(content=content, **dep) for dep in deps]
        )

    # Create the content artifact (links the .crate file to the content)
    relative_path = f"{name}/{name}-{vers}.crate"
    await ContentArtifact.objects.acreate(
        artifact=artifact, content=content, relative_path=relative_path
    )

    # Add the content to a new repository version
    await aadd_and_remove(
        repository_pk=repository.pk,
        add_content_units=[content.pk],
        remove_content_units=[],
    )
