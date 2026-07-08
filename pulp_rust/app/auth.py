"""Cargo token authentication for Cargo API endpoints."""

import hashlib

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from pulp_rust.app.models import RustCargoToken


class CargoTokenAuthentication(BaseAuthentication):
    """Authenticate Cargo requests via the Authorization header token."""

    def authenticate(self, request):
        token = request.META.get("HTTP_AUTHORIZATION")
        if not token or not token.startswith("crg_"):
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            cargo_token = RustCargoToken.objects.select_related("user").get(token_hash=token_hash)
        except RustCargoToken.DoesNotExist:
            raise AuthenticationFailed("invalid cargo token")
        cargo_token.last_used = timezone.now()
        cargo_token.save(update_fields=["last_used"])
        return (cargo_token.user, cargo_token)

    def authenticate_header(self, request):
        return "CargoToken"
