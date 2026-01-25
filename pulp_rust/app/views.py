import json
import logging

from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework.exceptions import Throttled
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect, get_object_or_404

from django.http.response import (
    Http404,
    HttpResponseNotFound,
    HttpResponse,
)
from drf_spectacular.utils import extend_schema
from dynaconf import settings
from pathlib import PurePath
from urllib.parse import urljoin

from pulpcore.plugin.util import get_domain

from pulp_rust.app.models import RustDistribution, RustRepository, RustContent
from pulp_rust.app.serializers import (
    IndexRootSerializer,
    RustContentSerializer,
)

log = logging.getLogger(__name__)

BASE_CONTENT_URL = urljoin(settings.CONTENT_ORIGIN, settings.CONTENT_PATH_PREFIX)
BASE_API_URL = urljoin(settings.CRATES_IO_API_HOSTNAME, "/pulp/cargo/")
CRATES_IO_API = "/api/v1/crates/"


class ApiMixin:
    """Mixin to get index specific info."""

    _distro = None

    @property
    def distribution(self):
        if not self._distro:
            self._distro = self.get_distribution(self.kwargs["repo"])
        return self._distro

    @staticmethod
    def get_distribution(repo):
        """Finds the distribution associated with this base_path."""
        distro_qs = RustDistribution.objects.select_related(
            "repository", "repository_version", "remote"
        )
        try:
            return distro_qs.get(base_path=repo, pulp_domain=get_domain())
        except ObjectDoesNotExist:
            raise Http404(f"No RustDistribution found for base_path {repo}")  # TODO: broken

    @staticmethod
    def get_repository_version(distribution):
        """Finds the repository version this distribution is serving."""
        rep = distribution.repository
        rep_version = distribution.repository_version
        if rep:
            return rep.latest_version()
        elif rep_version:
            return rep_version
        else:
            raise Http404("No repository associated with this index")

    @staticmethod
    def get_content(repository_version):
        """Returns queryset of the content in this repository version."""
        return RustContent.objects.filter(pk__in=repository_version.content)

    def get_rvc(self):
        """Takes the base_path and returns the repository_version and content."""
        if self.distribution.remote:
            if not self.distribution.repository:
                return None, None
        repo_ver = self.get_repository_version(self.distribution)
        content = self.get_content(repo_ver)
        return repo_ver, content

    def initial(self, request, *args, **kwargs):
        """Perform common initialization tasks for API endpoints."""
        super().initial(request, *args, **kwargs)
        domain_name = get_domain().name
        log.warning(self.kwargs)
        repo = self.kwargs["repo"]
        if settings.DOMAIN_ENABLED:
            self.base_content_url = urljoin(BASE_CONTENT_URL, f"pulp/cargo/{domain_name}/{repo}/")
            self.base_api_url = urljoin(BASE_API_URL, f"{domain_name}/{repo}/")
            self.base_download_url = urljoin(BASE_API_URL, f"{domain_name}/{repo}{CRATES_IO_API}")
        else:
            self.base_content_url = urljoin(BASE_CONTENT_URL, f"pulp/cargo/{repo}/")
            self.base_api_url = urljoin(BASE_API_URL, f"{repo}/")
            self.base_download_url = urljoin(BASE_API_URL, f"{repo}{CRATES_IO_API}")

    @classmethod
    def urlpattern(cls):
        """Mocking NamedModelViewSet behavior to get Cargo APIs to support RBAC access polices."""
        return f"pulp/cargo/{cls.endpoint_name}"


class CargoIndexApiViewSet(ApiMixin, ViewSet):
    """View for the Cargo JSON metadata endpoint."""

    endpoint_name = "api"
    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["retrieve"],
                "principal": "*",
                "effect": "allow",
            },
        ],
    }

    @extend_schema(
        tags=["Cargo: Metadata"],
        responses={200: RustContentSerializer},
        summary="Get package metadata",
    )
    def retrieve(self, request, path):
        """
        Retrieve crate metadata for the sparse protocol.

        The sparse protocol uses a directory structure based on crate name length:
        - 1 char: 1/{crate}
        - 2 chars: 2/{crate}
        - 3 chars: 3/{first-char}/{crate}
        - 4+ chars: {first-two}/{second-two}/{crate}

        Returns newline-delimited JSON, one version per line.
        """
        repo_ver, content = self.get_rvc()

        if content is None:
            return HttpResponseNotFound("No content available")

        # Extract crate name from the path
        meta_path = PurePath(path)
        crate_name = meta_path.name.lower()

        # Query for all versions of this crate
        crate_versions = content.filter(name=crate_name).order_by("vers")

        if not crate_versions.exists():
            return HttpResponseNotFound(f"Crate '{crate_name}' not found")

        # Build newline-delimited JSON response
        lines = []
        for crate_version in crate_versions:
            # Fetch dependencies for this version
            deps = []
            for dep in crate_version.dependencies.all():
                dep_obj = {
                    "name": dep.name,
                    "req": dep.req,
                    "features": dep.features,
                    "optional": dep.optional,
                    "default_features": dep.default_features,
                    "target": dep.target,
                    "kind": dep.kind,
                    "registry": dep.registry,
                    "package": dep.package,
                }
                deps.append(dep_obj)

            # Build the version object according to sparse protocol
            version_obj = {
                "name": crate_version.name,
                "vers": crate_version.vers,
                "deps": deps,
                "cksum": crate_version.cksum,
                "features": crate_version.features,
                "yanked": crate_version.yanked,
                "links": crate_version.links,
                "v": crate_version.v,
            }

            # Add optional fields only if present
            if crate_version.features2:
                version_obj["features2"] = crate_version.features2
            if crate_version.rust_version:
                version_obj["rust_version"] = crate_version.rust_version

            # Serialize to JSON and add to lines
            lines.append(json.dumps(version_obj))

        # Join with newlines and return as plain text
        response_text = "\n".join(lines)
        return HttpResponse(response_text, content_type="text/plain")


class IndexRoot(ApiMixin, ViewSet):
    """View for base_url of distribution."""

    endpoint_name = "root"
    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["retrieve"],
                "principal": "*",
                "effect": "allow",
            },
        ],
    }

    @extend_schema(responses={200: IndexRootSerializer}, summary="Get index info")
    def retrieve(self, request, repo):
        """Gets index route."""
        return Response(
            data={
                "dl": self.base_download_url,
                "api": self.base_api_url,
                "auth-required": False,
            }
        )


class CargoDownloadApiView(APIView):
    """
    ViewSet for interacting with Cargo's API API
    """

    model = RustRepository
    queryset = RustRepository.objects.all()

    lookup_field = "name"

    # Authentication disabled for now
    authentication_classes = []
    permission_classes = []

    def get_full_path(self, base_path, pulp_domain=None):  # TODO: replace with ApiMixin?
        if settings.DOMAIN_ENABLED:
            domain = pulp_domain or get_domain()
            return f"{domain.name}/{base_path}"
        return base_path

    def redirect_to_content_app(self, distribution, relative_path, request):
        scheme = request.META.get("HTTP_X_FORWARDED_PROTO", request.scheme)
        hostname = request.META.get("HTTP_X_FORWARDED_HOST", request.get_host())
        content_origin = f"{scheme}://{hostname}"
        return redirect(
            f"{content_origin}{settings.CONTENT_PATH_PREFIX}"
            f"{self.get_full_path(distribution.base_path)}/{relative_path}"
        )

    def get_repository_and_distributions(self, name):
        repository = get_object_or_404(RustRepository, name=name, pulp_domain=get_domain())
        distribution = get_object_or_404(
            RustDistribution, repository=repository, pulp_domain=get_domain()
        )
        return repository, distribution

    def get(self, request, name, version):
        """
        Responds to GET requests about packages by reference
        """
        repo, distro = self.get_repository_and_distributions(name)
        content = get_object_or_404(
            RustContent, name=name, vers=version, pk__in=repo.latest_version().content
        )
        relative_path = content.contentartifact_set.get().relative_path
        return self.redirect_to_content_app(distro, relative_path, request)


def has_task_completed(task):
    """
    Verify whether an immediate task ran properly.

    Returns:
        bool: True if the task ended successfully.

    Raises:
        Exception: If an error occured during the task's runtime.
        Throttled: If the task did not run due to resource constraints.

    """
    if task.state == "completed":
        task.delete()
        return True
    elif task.state == "canceled":
        raise Throttled()
    else:
        error = task.error
        task.delete()
        raise Exception(str(error))
