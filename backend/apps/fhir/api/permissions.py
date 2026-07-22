from rest_framework import permissions

from apps.fhir.services.resource_registry import FHIRResourceRegistry


class FHIRResourcePermission(permissions.BasePermission):
    """
    Enforces that the authenticated user has the necessary read/write capability
    for the given FHIR resource based on the ResourceRegistry and the request method.
    """

    def has_permission(self, request, view):
        # Allow DRF to handle authentication first
        if not request.user or not request.user.is_authenticated:
            return False

        resource_type = getattr(view, "fhir_resource_type", None)
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return False
        if not resource_type:
            # If the view doesn't declare a resource type, it might be a generic metadata endpoint
            return True

        required_capability = getattr(view, "required_capability", None)
        if required_capability:
            return request.user.has_capability(required_capability, tenant_id=tenant_id)

        try:
            registration = FHIRResourceRegistry.get_registration(resource_type)
        except Exception:
            return False

        if request.method in permissions.SAFE_METHODS:
            required_perm = registration.read_permission
            if required_perm and not request.user.has_capability(required_perm, tenant_id=tenant_id):
                return False
        else:
            required_perm = registration.write_permission
            if not required_perm or not request.user.has_capability(required_perm, tenant_id=tenant_id):
                return False

        return True

    def has_object_permission(self, request, view, obj):
        # We handle object level permissions / tenant isolation via the get_queryset
        # or explicit domain service checks instead of here, to ensure we never
        # query across tenants anyway.
        return True
