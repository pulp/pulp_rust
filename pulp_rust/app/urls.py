from django.conf import settings
from django.urls import path

from pulp_rust.app.views import IndexRoot, CargoIndexApiViewSet, CargoDownloadApiView

if settings.DOMAIN_ENABLED:
    CRATES_IO_URL = "pulp/cargo/<slug:pulp_domain>/<slug:repo>/"
else:
    CRATES_IO_URL = "pulp/cargo/<slug:repo>/"


urlpatterns = [
    path(
        CRATES_IO_URL + "api/v1/crates/<str:package>/<str:version>/<path:rest>",
        CargoDownloadApiView.as_view(),
        name="cargo-download-api",
    ),
    path(CRATES_IO_URL + "config.json", IndexRoot.as_view({"get": "retrieve"}), name="index-root"),
    path(
        CRATES_IO_URL + "<path:path>",
        CargoIndexApiViewSet.as_view({"get": "retrieve"}),
        name="cargo-index-api",
    ),
]
