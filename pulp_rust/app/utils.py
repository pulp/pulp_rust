import tarfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def extract_cargo_toml(crate_path, crate_name, version):
    """Extract and parse Cargo.toml from a .crate tarball."""
    expected_path = f"{crate_name}-{version}/Cargo.toml"
    with tarfile.open(crate_path, "r:gz") as tar:
        cargo_toml_file = tar.extractfile(expected_path)
        if cargo_toml_file is None:
            raise FileNotFoundError(f"No Cargo.toml found in {crate_path} at {expected_path}")
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
