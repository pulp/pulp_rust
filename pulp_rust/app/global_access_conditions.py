from django.conf import settings

from pulp_rust.app.models import RustCargoToken


def has_distributions_param_model_or_domain_or_obj_perms(request, view, action, permission):
    """Check the permission against every distribution in the `distributions` parameter."""
    if request.user.has_perm(permission):
        return True
    if settings.DOMAIN_ENABLED and request.user.has_perm(permission, obj=request.pulp_domain):
        return True

    serializer = view.get_serializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return all(
        request.user.has_perm(permission, distribution)
        for distribution in serializer.validated_data.get("distributions", [])
    )


def can_read_distribution(request, distribution):
    """Whether the request may read the index and crates of a Rust distribution."""
    if not distribution.cargo_auth_required:
        return True
    token = request.auth
    if isinstance(token, RustCargoToken):
        scoped_distributions = set(token.distributions.values_list("pk", flat=True))
        if scoped_distributions and distribution.pk not in scoped_distributions:
            return False
    permission = "rust.view_rustdistribution"
    user = request.user
    if user.has_perm(permission) or user.has_perm(permission, obj=distribution):
        return True
    return settings.DOMAIN_ENABLED and user.has_perm(permission, obj=request.pulp_domain)
