import re
import tarfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def extract_cargo_toml(fileobj, crate_name, version):
    """Extract and parse Cargo.toml from a .crate tarball.

    Args:
        fileobj: A file-like object containing the .crate tarball data.
        crate_name: The crate name (used to locate Cargo.toml inside the tarball).
        version: The crate version (used to locate Cargo.toml inside the tarball).
    """
    expected_path = f"{crate_name}-{version}/Cargo.toml"
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
        cargo_toml_file = tar.extractfile(expected_path)
        if cargo_toml_file is None:
            raise FileNotFoundError(f"No Cargo.toml found at {expected_path}")
        return tomllib.load(cargo_toml_file)


def _normalize_req(version_str):
    """Normalize a Cargo version requirement to its explicit form.

    In Cargo.toml, a bare version like "1.0" is shorthand for "^1.0".
    The index format uses the explicit form with the comparator prefix.
    """
    if not version_str or version_str == "*":
        return version_str
    # Already has a comparator prefix
    if version_str[0] in ("^", "~", "=", ">", "<"):
        return version_str
    return f"^{version_str}"


def parse_dep(name, spec, kind="normal", target=None):
    """Convert a single Cargo.toml dependency entry to index format."""
    if isinstance(spec, str):
        # Simple form: dep = "1.0"
        return {
            "name": name,
            "req": _normalize_req(spec),
            "features": [],
            "optional": False,
            "default_features": True,
            "target": target,
            "kind": kind,
            "registry": None,
            "package": None,
        }

    # Table form: dep = { version = "1.0", optional = true, ... }
    dep = {
        "name": name,
        "req": _normalize_req(spec.get("version", "*")),
        "features": spec.get("features", []),
        "optional": spec.get("optional", False),
        "default_features": spec.get("default-features", True),
        "target": target,
        "kind": kind,
        "registry": spec.get("registry"),
        "package": None,
    }
    # If the dep was renamed, "name" in the index is the alias (the key),
    # and "package" is the real crate name
    if "package" in spec:
        dep["package"] = spec["package"]
    return dep


def extract_dependencies(cargo_toml):
    """Extract all dependencies from a parsed Cargo.toml into index format."""
    deps = []

    for name, spec in cargo_toml.get("dependencies", {}).items():
        deps.append(parse_dep(name, spec, kind="normal"))

    for name, spec in cargo_toml.get("dev-dependencies", {}).items():
        deps.append(parse_dep(name, spec, kind="dev"))

    for name, spec in cargo_toml.get("build-dependencies", {}).items():
        deps.append(parse_dep(name, spec, kind="build"))

    # Platform-specific dependencies: [target.'cfg(...)'.dependencies]
    for target, target_deps in cargo_toml.get("target", {}).items():
        for name, spec in target_deps.get("dependencies", {}).items():
            deps.append(parse_dep(name, spec, kind="normal", target=target))
        for name, spec in target_deps.get("dev-dependencies", {}).items():
            deps.append(parse_dep(name, spec, kind="dev", target=target))
        for name, spec in target_deps.get("build-dependencies", {}).items():
            deps.append(parse_dep(name, spec, kind="build", target=target))

    return deps


CRATE_NAME_MAX_LENGTH = 64
CRATE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(-[0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*)?"
    r"(\+[0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*)?$"
)


def validate_crate_name(name):
    """Validate a crate name.

    Enforces the following rules:
    - Must start with an ASCII letter and contain only ASCII alphanumeric
      characters, hyphens, or underscores (Cargo spec, via ``cargo new``).
    - Must not exceed 64 characters (crates.io policy, not in the Cargo spec).

    Returns None if valid, or an error message string if invalid.
    """
    if not name:
        return "crate name must not be empty"
    if len(name) > CRATE_NAME_MAX_LENGTH:
        return f"crate name exceeds maximum length of {CRATE_NAME_MAX_LENGTH} characters"
    if not CRATE_NAME_RE.match(name):
        return (
            "crate name must start with an ASCII letter and contain only "
            "ASCII alphanumeric characters, hyphens, or underscores"
        )
    return None


def validate_crate_version(version):
    """Validate a crate version per SemVer 2.0.0 (required by Cargo spec).

    Returns None if valid, or an error message string if invalid.
    """
    if not version:
        return "crate version must not be empty"
    if not SEMVER_RE.match(version):
        return f"invalid semver: `{version}` " "(expected MAJOR.MINOR.PATCH[-prerelease][+build])"
    return None


def strip_semver_build_metadata(version):
    """Strip build metadata from a SemVer version string.

    Per SemVer 2.0.0, versions that differ only in build metadata have equal
    precedence.  The Cargo registry spec requires that indexes treat such
    versions as identical (e.g. ``1.0.0`` and ``1.0.0+build1`` must collide).
    """
    return version.split("+", 1)[0]


def canonicalize_crate_name(name):
    """Canonicalize a crate name for uniqueness comparison.

    Crate names are case-insensitive and hyphens and underscores are treated
    as equivalent (Cargo spec).
    """
    return name.lower().replace("-", "_")
