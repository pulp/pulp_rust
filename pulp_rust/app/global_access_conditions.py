from django.conf import settings


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
