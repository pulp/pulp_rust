from gettext import gettext as _

from rest_framework import serializers

from pulpcore.plugin import models as core_models
from pulpcore.plugin import serializers as core_serializers

from . import models


class RustDependencySerializer(serializers.ModelSerializer):
    """
    Serializer for RustDependency.

    Represents a single dependency entry from the Cargo package index.
    """

    name = serializers.CharField(
        help_text=_("Dependency name as used in code (may be renamed via 'package' field)")
    )

    req = serializers.CharField(
        help_text=_("Version requirement string (e.g., '^1.0', '>=0.2.3,<0.3')")
    )

    features = serializers.ListField(
        child=serializers.CharField(),
        default=list,
        required=False,
        help_text=_("List of feature flags to enable for this dependency"),
    )

    optional = serializers.BooleanField(
        default=False, required=False, help_text=_("Whether this is an optional dependency")
    )

    default_features = serializers.BooleanField(
        default=True,
        required=False,
        help_text=_("Whether to enable the dependency's default features"),
    )

    target = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=_("Platform-specific target (e.g., 'cfg(unix)', 'cfg(windows)')"),
    )

    kind = serializers.ChoiceField(
        choices=[("normal", "Normal"), ("dev", "Development"), ("build", "Build")],
        default="normal",
        required=False,
        help_text=_(
            "Dependency type: 'normal' (runtime), 'dev' (development), or 'build' (build script)"
        ),
    )

    registry = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=_("Alternative registry URL if dependency is from a different registry"),
    )

    package = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=_("Original crate name if the dependency was renamed"),
    )

    class Meta:
        model = models.RustDependency
        fields = (
            "name",
            "req",
            "features",
            "optional",
            "default_features",
            "target",
            "kind",
            "registry",
            "package",
        )


class RustContentSerializer(core_serializers.SingleArtifactContentSerializer):
    """
    Serializer for RustContent (Cargo package version).

    Represents a single version of a Rust crate as defined in the Cargo registry
    index specification. Includes package metadata, dependencies, and features.
    """

    name = serializers.CharField(help_text=_("Package name (crate name)"))

    vers = serializers.CharField(help_text=_("Semantic version string (SemVer 2.0.0)"))

    dependencies = RustDependencySerializer(
        many=True, required=False, help_text=_("List of dependencies for this package version")
    )

    cksum = serializers.CharField(help_text=_("SHA256 checksum of the .crate file (tarball)"))

    features = serializers.JSONField(
        default=dict,
        required=False,
        help_text=_(
            "Feature flags mapping - maps feature names to lists of features/dependencies "
            "they enable"
        ),
    )

    features2 = serializers.JSONField(
        default=dict,
        required=False,
        allow_null=True,
        help_text=_("Extended feature syntax support (newer registry format)"),
    )

    yanked = serializers.BooleanField(
        default=False,
        required=False,
        help_text=_("Whether this version has been yanked (removed from normal use)"),
    )

    links = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=_("Name of native library this package links to (from Cargo.toml 'links' field)"),
    )

    v = serializers.IntegerField(
        default=1, required=False, help_text=_("Schema version of the index entry format")
    )
    rust_version = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=_("Minimum Rust compiler version required (MSRV)"),
    )

    def create(self, validated_data):
        """Create RustContent and related dependencies."""
        dependencies_data = validated_data.pop("dependencies", [])
        content = super().create(validated_data)

        # Create dependency records
        for dep_data in dependencies_data:
            models.RustDependency.objects.create(content=content, **dep_data)

        return content

    def update(self, instance, validated_data):
        """Update RustContent and related dependencies."""
        dependencies_data = validated_data.pop("dependencies", None)

        instance = super().update(instance, validated_data)

        if dependencies_data is not None:
            # Replace all dependencies
            instance.dependencies.all().delete()
            for dep_data in dependencies_data:
                models.RustDependency.objects.create(content=instance, **dep_data)

        return instance

    class Meta:
        fields = core_serializers.SingleArtifactContentSerializer.Meta.fields + (
            "name",
            "vers",
            "dependencies",
            "cksum",
            "features",
            "features2",
            "yanked",
            "links",
            "v",
            "rust_version",
        )
        model = models.RustContent


class RustRemoteSerializer(core_serializers.RemoteSerializer):
    """
    A Serializer for RustRemote.

    Add any new fields if defined on RustRemote.
    Similar to the example above, in RustContentSerializer.
    Additional validators can be added to the parent validators list

    For example::

    class Meta:
        validators = core_serializers.RemoteSerializer.Meta.validators
            + [myValidator1, myValidator2]

    By default the 'policy' field in core_serializers.RemoteSerializer only validates the choice
    'immediate'. To add on-demand support for more 'policy' options, e.g. 'streamed' or
    'on_demand', re-define the 'policy' option as follows::

    policy = serializers.ChoiceField(
        help_text="The policy to use when downloading content. The possible values include: "
                  "'immediate', 'on_demand', and 'streamed'. 'immediate' is the default.",
        choices=models.Remote.POLICY_CHOICES,
        default=models.Remote.IMMEDIATE
    )
    """

    class Meta:
        fields = core_serializers.RemoteSerializer.Meta.fields
        model = models.RustRemote


class RustRepositorySerializer(core_serializers.RepositorySerializer):
    """
    A Serializer for RustRepository.

    Add any new fields if defined on RustRepository.
    Similar to the example above, in RustContentSerializer.
    Additional validators can be added to the parent validators list

    For example::

    class Meta:
        validators = core_serializers.RepositorySerializer.Meta.validators
            + [myValidator1, myValidator2]
    """

    class Meta:
        fields = core_serializers.RepositorySerializer.Meta.fields
        model = models.RustRepository


class RustDistributionSerializer(core_serializers.DistributionSerializer):
    """
    A Serializer for RustDistribution.

    Add any new fields if defined on RustDistribution.
    Similar to the example above, in RustContentSerializer.
    Additional validators can be added to the parent validators list

    For example::

    class Meta:
        validators = core_serializers.DistributionSerializer.Meta.validators + [
            myValidator1, myValidator2]
    """

    allow_uploads = serializers.BooleanField(
        default=True, help_text=_("Allow packages to be uploaded to this index.")
    )
    remote = core_serializers.DetailRelatedField(
        required=False,
        help_text=_("Remote that can be used to fetch content when using pull-through caching."),
        view_name_pattern=r"remotes(-.*/.*)?-detail",
        queryset=core_models.Remote.objects.all(),
        allow_null=True,
    )

    class Meta:
        fields = core_serializers.DistributionSerializer.Meta.fields + ("allow_uploads", "remote")
        model = models.RustDistribution
