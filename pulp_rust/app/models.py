import json
import urllib.request
from logging import getLogger

from django.db import models

from pulpcore.plugin.models import (
    Content,
    Remote,
    Repository,
    Distribution,
)
from pulpcore.plugin.util import get_domain_pk

logger = getLogger(__name__)


def _strip_sparse_prefix(url):
    """Strip the sparse+ prefix from a Cargo registry URL."""
    if url.startswith("sparse+"):
        return url[len("sparse+") :]
    return url


def _parse_crate_relative_path(relative_path):
    """
    Parse crate name and version from a relative path.

    Expected format: {name}/{name}-{version}.crate
    Returns: (crate_name, version)
    """
    # "serde/serde-1.0.0.crate" -> "serde-1.0.0.crate"
    filename = relative_path.rsplit("/", 1)[-1]
    # "serde-1.0.0.crate" -> "serde-1.0.0"
    stem = filename[: -len(".crate")]
    # "serde/serde-1.0.0.crate" -> "serde"
    crate_name = relative_path.split("/", 1)[0]
    # "serde-1.0.0" -> "1.0.0"
    version = stem[len(crate_name) + 1 :]
    return crate_name, version


class RustContent(Content):
    """
    The "rust" content type representing a Cargo package version.

    This model represents a single version of a Rust crate as defined in the
    Cargo registry index specification. Each instance corresponds to one line
    in a package's index file.

    Fields:
        name: The package name (crate name)
        vers: The semantic version string (SemVer 2.0.0)
        cksum: SHA256 checksum of the .crate file (tarball)
        yanked: Whether this version has been yanked (removed from normal use)
        features: JSON object mapping feature names to their dependencies
        features2: JSON object with extended feature syntax support
        links: Value from Cargo.toml manifest 'links' field (for native library linking)
        rust_version: Minimum Rust version required to compile this package
        v: Schema version of the index format (integer)
    """

    TYPE = "rust"
    repo_key_fields = ("name", "vers")

    # Package name - alphanumeric characters, hyphens, and underscores allowed
    name = models.CharField(max_length=255, blank=False, null=False, db_index=True)

    # Semantic version string following SemVer 2.0.0 specification
    vers = models.CharField(max_length=64, blank=False, null=False, db_index=True)

    # SHA256 checksum (hex-encoded) of the .crate tarball file for verification
    cksum = models.CharField(max_length=64, blank=False, null=False, db_index=True)

    # Indicates if this version has been yanked (deprecated/removed from use)
    # Yanked versions can still be used by existing Cargo.lock files but won't be selected
    # for new builds
    yanked = models.BooleanField(default=False)

    # Feature flags and compatibility
    # Maps feature names to lists of features/dependencies they enable
    # Example: {"default": ["std"], "std": [], "serde": ["dep:serde"]}
    features = models.JSONField(default=dict, blank=True)

    # Extended feature syntax introduced in newer registry versions
    # Supports more complex feature dependency expressions
    features2 = models.JSONField(default=dict, blank=True, null=True)

    # Name of native library this package links to (from Cargo.toml 'links' field)
    # Used to prevent multiple packages from linking the same native library
    links = models.CharField(max_length=255, blank=True, null=True)

    # Minimum Rust compiler version required (MSRV - Minimum Supported Rust Version)
    # Example: "1.56.0"
    rust_version = models.CharField(max_length=32, blank=True, null=True)

    # Schema version of the index entry format
    # Allows for future format evolution while maintaining backward compatibility
    v = models.IntegerField(default=1)

    _pulp_domain = models.ForeignKey("core.Domain", default=get_domain_pk, on_delete=models.PROTECT)

    @staticmethod
    def init_from_artifact_and_relative_path(artifact, relative_path):
        """
        Create an unsaved RustContent from a downloaded .crate artifact.

        Called by pulpcore's content handler during pull-through caching.
        Only populates name, version, and checksum -- dependency and feature
        metadata is served from the upstream sparse index via the proxy.
        """
        crate_name, version = _parse_crate_relative_path(relative_path)
        return RustContent(
            name=crate_name,
            vers=version,
            cksum=artifact.sha256,
        )

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        unique_together = (("name", "vers", "_pulp_domain"),)


class RustDependency(models.Model):
    """
    Represents a dependency of a Cargo package version.

    Each RustContent (package version) can have multiple dependencies.
    Dependencies are stored as separate records to enable efficient querying
    and relationship tracking.

    Fields:
        content: The package version that has this dependency
        name: The dependency name as used in code (may be renamed via 'package')
        req: Version requirement string (e.g., "^1.0", ">=0.2.3,<0.3")
        features: List of feature flags to enable for this dependency
        optional: Whether this is an optional dependency
        default_features: Whether to enable the dependency's default features
        target: Platform-specific conditional compilation target (e.g., "cfg(unix)")
        kind: Dependency type - "normal", "dev", or "build"
        registry: Alternative registry URL if dependency is from a different registry
        package: Original package name if dependency was renamed in Cargo.toml
    """

    # The package version that declares this dependency
    content = models.ForeignKey(RustContent, on_delete=models.CASCADE, related_name="dependencies")

    # Name of the dependency as used in the code (may differ from package name if renamed)
    name = models.CharField(max_length=255, blank=False, null=False)

    # Version requirement string using Cargo's version requirement syntax
    # Examples: "1.0", "^1.2.3", ">=1.0.0,<2.0.0", "*"
    req = models.CharField(max_length=255, blank=False, null=False)

    # List of feature flags to enable for this dependency
    # Example: ["serde", "std"]
    features = models.JSONField(default=list, blank=True)

    # If true, this dependency is only included when explicitly requested via features
    # Optional dependencies can be enabled as features themselves
    optional = models.BooleanField(default=False)

    # Whether to enable the dependency's default feature set
    # Setting to false allows for minimal builds
    default_features = models.BooleanField(default=True)

    # Platform-specific target configuration (cfg expression)
    # Example: "cfg(windows)", "cfg(target_arch = \"x86_64\")"
    # If set, dependency only applies when the target matches
    target = models.CharField(max_length=255, blank=True, null=True)

    # Type of dependency - determines when it's required during the build process
    kind = models.CharField(
        max_length=16,
        choices=[
            ("normal", "Normal"),  # Regular runtime dependency
            ("dev", "Development"),  # Development/test-only dependency
            ("build", "Build"),  # Build script dependency
        ],
        default="normal",
    )

    # @TODO: I suspect this isn't needed
    # URL of alternative registry if dependency comes from a non-default registry
    # Null means the dependency is from the same registry as the parent package
    registry = models.CharField(max_length=512, blank=True, null=True)

    # Original crate name if the dependency was renamed
    # Example: if 'use foo' but package is 'bar', name='foo', package='bar'
    package = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        verbose_name_plural = "rust dependencies"
        indexes = [
            models.Index(fields=["content", "kind"]),
            models.Index(fields=["name"]),
        ]


class RustRemote(Remote):
    """
    A Remote for RustContent.

    The `url` field should point to the sparse index root, optionally prefixed
    with `sparse+` (e.g. `sparse+https://index.crates.io/`).
    """

    TYPE = "rust"

    def get_remote_artifact_url(self, relative_path=None, request=None):
        """
        Construct the upstream download URL for a .crate file.

        Fetches config.json from the index root to obtain the `dl` template,
        then substitutes {crate} and {version} markers per the Cargo spec.
        """
        if relative_path is None or not relative_path.endswith(".crate"):
            return None

        crate_name, version = _parse_crate_relative_path(relative_path)
        index_url = _strip_sparse_prefix(self.url).rstrip("/")

        # TODO: Cache the config.json response to avoid fetching it on every request.
        config_url = f"{index_url}/config.json"
        response = urllib.request.urlopen(config_url)
        config = json.loads(response.read())
        dl_template = config["dl"]

        if "{crate}" in dl_template or "{version}" in dl_template:
            return dl_template.replace("{crate}", crate_name).replace("{version}", version)
        else:
            # No markers: per Cargo spec, append /{crate}/{version}/download
            return f"{dl_template.rstrip('/')}/{crate_name}/{version}/download"

    @staticmethod
    def get_remote_artifact_content_type(relative_path=None):
        """Return the content type for the given relative path."""
        if relative_path and relative_path.endswith(".crate"):
            return RustContent
        return None

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"


class RustRepository(Repository):
    """
    A Repository for RustContent.
    """

    TYPE = "rust"

    CONTENT_TYPES = [RustContent]
    REMOTE_TYPES = [RustRemote]
    PULL_THROUGH_SUPPORTED = True

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"


class RustDistribution(Distribution):
    """
    A Distribution for RustContent.

    Define any additional fields for your new distribution if needed.
    """

    TYPE = "rust"

    allow_uploads = models.BooleanField(default=True)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
