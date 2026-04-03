"""Stub authentication for Cargo API endpoints.

This is a temporary placeholder — it validates the Authorization header against
a hardcoded token so that state-changing endpoints (publish, yank, unyank) are
not completely open.  It will be replaced by proper token-based auth later.
"""

import functools
import json

from django.http import HttpResponse

STUB_TOKEN = "i_understand_that_pulp_rust_does_not_support_proper_auth_yet"


def require_cargo_token(view_method):
    """Decorator that validates the Cargo Authorization header against the stub token.

    Returns a 403 with a Cargo-style JSON error if the token is missing or incorrect.
    """

    @functools.wraps(view_method)
    def wrapper(self, request, *args, **kwargs):
        token = request.META.get("HTTP_AUTHORIZATION")
        if token == STUB_TOKEN:
            return view_method(self, request, *args, **kwargs)
        if not token:
            detail = "this endpoint requires an authorization token"
        else:
            detail = "invalid authorization token"
        return HttpResponse(
            json.dumps({"errors": [{"detail": detail}]}),
            content_type="application/json",
            status=403,
        )

    return wrapper
