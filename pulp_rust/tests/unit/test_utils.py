"""Unit tests for pulp_rust.app.utils."""

import io
import tarfile
import tempfile

import django
import pytest

django.setup()

from pulp_rust.app.utils import extract_cargo_toml, extract_dependencies, parse_dep  # noqa: E402


def _make_crate_tarball(crate_name, version, cargo_toml_bytes):
    """Create a .crate (gzipped tarball) in a temp file and return its path."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"{crate_name}-{version}/Cargo.toml")
        info.size = len(cargo_toml_bytes)
        tar.addfile(info, io.BytesIO(cargo_toml_bytes))
    tmp = tempfile.NamedTemporaryFile(suffix=".crate", delete=False)
    tmp.write(buf.getvalue())
    tmp.flush()
    return tmp.name


class TestParseDep:
    def test_simple_string_spec(self):
        result = parse_dep("serde", "1.0")
        assert result == {
            "name": "serde",
            "req": "^1.0",
            "features": [],
            "optional": False,
            "default_features": True,
            "target": None,
            "kind": "normal",
            "registry": None,
            "package": None,
        }

    def test_table_spec_minimal(self):
        result = parse_dep("serde", {"version": "1.0"})
        assert result["name"] == "serde"
        assert result["req"] == "^1.0"
        assert result["optional"] is False
        assert result["default_features"] is True
        assert result["features"] == []
        assert result["package"] is None

    def test_table_spec_all_fields(self):
        spec = {
            "version": "^1.2",
            "features": ["derive", "std"],
            "optional": True,
            "default-features": False,
            "registry": "https://my-registry.example.com/",
            "package": "serde_real",
        }
        result = parse_dep("my_serde", spec)
        assert result["name"] == "my_serde"
        assert result["req"] == "^1.2"
        assert result["features"] == ["derive", "std"]
        assert result["optional"] is True
        assert result["default_features"] is False
        assert result["registry"] == "https://my-registry.example.com/"
        assert result["package"] == "serde_real"

    def test_table_spec_no_version_defaults_to_star(self):
        result = parse_dep("foo", {"optional": True})
        assert result["req"] == "*"

    def test_kind_propagated(self):
        result = parse_dep("cc", "1.0", kind="build")
        assert result["kind"] == "build"

    def test_target_propagated(self):
        result = parse_dep("winapi", "0.3", target="cfg(windows)")
        assert result["target"] == "cfg(windows)"

    def test_dev_kind(self):
        result = parse_dep("criterion", "0.4", kind="dev")
        assert result["kind"] == "dev"

    def test_renamed_dep(self):
        spec = {"version": "1.0", "package": "original_name"}
        result = parse_dep("alias", spec)
        assert result["name"] == "alias"
        assert result["package"] == "original_name"

    def test_bare_version_gets_caret_prefix(self):
        assert parse_dep("foo", "1.2.3")["req"] == "^1.2.3"

    def test_tilde_version_preserved(self):
        assert parse_dep("foo", "~1.2")["req"] == "~1.2"

    def test_exact_version_preserved(self):
        assert parse_dep("foo", "=1.0.0")["req"] == "=1.0.0"

    def test_comparison_version_preserved(self):
        assert parse_dep("foo", ">=1.0,<2.0")["req"] == ">=1.0,<2.0"

    def test_wildcard_preserved(self):
        assert parse_dep("foo", "*")["req"] == "*"

    def test_table_bare_version_gets_caret(self):
        result = parse_dep("foo", {"version": "0.3"})
        assert result["req"] == "^0.3"


class TestExtractDependencies:
    def test_empty_toml(self):
        assert extract_dependencies({}) == []

    def test_normal_deps(self):
        cargo_toml = {
            "dependencies": {
                "serde": "1.0",
                "log": {"version": "0.4", "features": ["std"]},
            }
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 2
        by_name = {d["name"]: d for d in deps}
        assert by_name["serde"]["req"] == "^1.0"
        assert by_name["serde"]["kind"] == "normal"
        assert by_name["log"]["features"] == ["std"]

    def test_dev_deps(self):
        cargo_toml = {
            "dev-dependencies": {
                "criterion": "0.4",
            }
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 1
        assert deps[0]["kind"] == "dev"
        assert deps[0]["name"] == "criterion"

    def test_build_deps(self):
        cargo_toml = {
            "build-dependencies": {
                "cc": "1.0",
            }
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 1
        assert deps[0]["kind"] == "build"

    def test_target_specific_deps(self):
        cargo_toml = {
            "target": {
                "cfg(windows)": {
                    "dependencies": {"winapi": "0.3"},
                },
                "cfg(unix)": {
                    "dependencies": {"libc": "0.2"},
                    "dev-dependencies": {"nix": "0.26"},
                },
            }
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 3
        by_name = {d["name"]: d for d in deps}
        assert by_name["winapi"]["target"] == "cfg(windows)"
        assert by_name["winapi"]["kind"] == "normal"
        assert by_name["libc"]["target"] == "cfg(unix)"
        assert by_name["nix"]["target"] == "cfg(unix)"
        assert by_name["nix"]["kind"] == "dev"

    def test_mixed_dep_types(self):
        cargo_toml = {
            "dependencies": {"serde": "1.0"},
            "dev-dependencies": {"criterion": "0.4"},
            "build-dependencies": {"cc": "1.0"},
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 3
        kinds = {d["name"]: d["kind"] for d in deps}
        assert kinds == {"serde": "normal", "criterion": "dev", "cc": "build"}

    def test_target_build_deps(self):
        cargo_toml = {
            "target": {
                "cfg(windows)": {
                    "build-dependencies": {"vcpkg": "0.2"},
                }
            }
        }
        deps = extract_dependencies(cargo_toml)
        assert len(deps) == 1
        assert deps[0]["name"] == "vcpkg"
        assert deps[0]["kind"] == "build"
        assert deps[0]["target"] == "cfg(windows)"


class TestExtractCargoToml:
    def test_basic_extraction(self):
        toml_content = b'[package]\nname = "foo"\nversion = "1.0.0"\n'
        path = _make_crate_tarball("foo", "1.0.0", toml_content)
        result = extract_cargo_toml(path, "foo", "1.0.0")
        assert result["package"]["name"] == "foo"
        assert result["package"]["version"] == "1.0.0"

    def test_with_dependencies(self):
        toml_content = (
            b'[package]\nname = "bar"\nversion = "0.1.0"\n' b'\n[dependencies]\nserde = "1.0"\n'
        )
        path = _make_crate_tarball("bar", "0.1.0", toml_content)
        result = extract_cargo_toml(path, "bar", "0.1.0")
        assert "serde" in result["dependencies"]

    def test_with_features(self):
        toml_content = (
            b'[package]\nname = "baz"\nversion = "2.0.0"\n'
            b'\n[features]\ndefault = ["std"]\nstd = []\n'
        )
        path = _make_crate_tarball("baz", "2.0.0", toml_content)
        result = extract_cargo_toml(path, "baz", "2.0.0")
        assert result["features"] == {"default": ["std"], "std": []}

    def test_missing_cargo_toml_raises(self):
        # A .crate without Cargo.toml is invalid and should error
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"hello"
            info = tarfile.TarInfo(name="foo-1.0.0/README.md")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        tmp = tempfile.NamedTemporaryFile(suffix=".crate", delete=False)
        tmp.write(buf.getvalue())
        tmp.flush()

        with pytest.raises(KeyError):
            extract_cargo_toml(tmp.name, "foo", "1.0.0")

    def test_with_rust_version(self):
        toml_content = b'[package]\nname = "qux"\nversion = "1.0.0"\nrust-version = "1.56.0"\n'
        path = _make_crate_tarball("qux", "1.0.0", toml_content)
        result = extract_cargo_toml(path, "qux", "1.0.0")
        assert result["package"]["rust-version"] == "1.56.0"

    def test_with_links(self):
        toml_content = b'[package]\nname = "zlib-sys"\nversion = "0.1.0"\nlinks = "z"\n'
        path = _make_crate_tarball("zlib-sys", "0.1.0", toml_content)
        result = extract_cargo_toml(path, "zlib-sys", "0.1.0")
        assert result["package"]["links"] == "z"
