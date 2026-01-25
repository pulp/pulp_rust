from django.db import transaction
from django_filters import CharFilter, BooleanFilter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from pulpcore.plugin.viewsets import RemoteFilter
from pulpcore.plugin import viewsets as core
from pulpcore.plugin.actions import ModifyRepositoryActionMixin
from pulpcore.plugin.serializers import (
    AsyncOperationResponseSerializer,
    RepositorySyncURLSerializer,
)
from pulpcore.plugin.tasking import dispatch
from pulpcore.plugin.models import ContentArtifact

from . import models, serializers, tasks


class RustContentFilter(core.ContentFilter):
    """
    FilterSet for RustContent (Cargo packages).

    Provides filtering capabilities for package name, version, and yanked status.
    """

    # Filter by exact package name
    name = CharFilter(field_name="name")

    # Filter by exact version string
    vers = CharFilter(field_name="vers")

    # Filter by checksum
    cksum = CharFilter(field_name="cksum")

    # Filter by yanked status
    yanked = BooleanFilter(field_name="yanked")

    # Filter by minimum Rust version requirement
    rust_version = CharFilter(field_name="rust_version")

    class Meta:
        model = models.RustContent
        fields = [
            "name",
            "vers",
            "cksum",
            "yanked",
            "rust_version",
        ]


class RustContentViewSet(core.ContentViewSet):
    """
    ViewSet for RustContent (Cargo package versions).

    Provides CRUD operations for Cargo package metadata including:
    - Package name and version
    - Dependencies with version requirements
    - Feature flags
    - Checksum verification
    - Yanked status

    API endpoint: /pulp/api/v3/content/rust/packages/
    """

    endpoint_name = "packages"
    queryset = models.RustContent.objects.prefetch_related("dependencies").all()
    serializer_class = serializers.RustContentSerializer
    filterset_class = RustContentFilter

    @transaction.atomic
    def create(self, request):
        """
        Create a new RustContent (Cargo package version).

        This handles creation of the package metadata along with its associated
        artifact (.crate file) and dependencies.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Extract artifact from validated data
        _artifact = serializer.validated_data.pop("_artifact", None)

        # Create the content (this also creates dependencies via serializer)
        content = serializer.save()

        # Associate the .crate file artifact with the content
        if content.pk and _artifact:
            # The relative path for the .crate file follows Cargo's naming convention:
            # {name}/{name}-{version}.crate
            relative_path = f"{content.name}/{content.name}-{content.vers}.crate"

            ContentArtifact.objects.create(
                artifact=_artifact, content=content, relative_path=relative_path
            )

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class RustRemoteFilter(RemoteFilter):
    """
    A FilterSet for RustRemote.
    """

    class Meta:
        model = models.RustRemote
        fields = [
            # ...
        ]


class RustRemoteViewSet(core.RemoteViewSet):
    """
    A ViewSet for RustRemote.

    Similar to the RustContentViewSet above, define endpoint_name,
    queryset and serializer, at a minimum.
    """

    endpoint_name = "rust"
    queryset = models.RustRemote.objects.all()
    serializer_class = serializers.RustRemoteSerializer


class RustRepositoryViewSet(core.RepositoryViewSet, ModifyRepositoryActionMixin):
    """
    A ViewSet for RustRepository.

    Similar to the RustContentViewSet above, define endpoint_name,
    queryset and serializer, at a minimum.
    """

    endpoint_name = "rust"
    queryset = models.RustRepository.objects.all()
    serializer_class = serializers.RustRepositorySerializer

    # This decorator is necessary since a sync operation is asyncrounous and returns
    # the id and href of the sync task.
    @extend_schema(
        description="Trigger an asynchronous task to sync content.",
        summary="Sync from remote",
        responses={202: AsyncOperationResponseSerializer},
    )
    @action(detail=True, methods=["post"], serializer_class=RepositorySyncURLSerializer)
    def sync(self, request, pk):
        """
        Dispatches a sync task.
        """
        repository = self.get_object()
        serializer = RepositorySyncURLSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        remote = serializer.validated_data.get("remote")
        mirror = serializer.validated_data.get("mirror")

        result = dispatch(
            tasks.synchronize,
            [repository, remote],
            kwargs={
                "remote_pk": str(remote.pk),
                "repository_pk": str(repository.pk),
                "mirror": mirror,
            },
        )
        return core.OperationPostponedResponse(result, request)

    @extend_schema(
        description="Trigger an asynchronous task to add cached content to a repository.",
        summary="Add cached content",
        responses={202: AsyncOperationResponseSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        serializer_class=serializers.RepositoryAddCachedContentSerializer,
    )
    def add_cached_content(self, request, pk):
        """
        Add to the repository any new content that was cached using the remote since the last
        repository version was created.

        The ``repository`` field has to be provided.
        """
        serializer = serializers.RepositoryAddCachedContentSerializer(
            data=request.data, context={"request": request, "repository_pk": pk}
        )
        serializer.is_valid(raise_exception=True)

        repository = self.get_object()
        remote = serializer.validated_data.get("remote", repository.remote)

        result = dispatch(
            tasks.add_cached_content_to_repository,
            shared_resources=[remote],
            exclusive_resources=[repository],
            kwargs={
                "remote_pk": str(remote.pk),
                "repository_pk": str(repository.pk),
            },
        )
        return core.OperationPostponedResponse(result, request)


class RustRepositoryVersionViewSet(core.RepositoryVersionViewSet):
    """
    A ViewSet for a RustRepositoryVersion represents a single
    Rust repository version.
    """

    parent_viewset = RustRepositoryViewSet


class RustDistributionViewSet(core.DistributionViewSet):
    """
    A ViewSet for RustDistribution.

    Similar to the RustContentViewSet above, define endpoint_name,
    queryset and serializer, at a minimum.
    """

    endpoint_name = "rust"
    queryset = models.RustDistribution.objects.all()
    serializer_class = serializers.RustDistributionSerializer
