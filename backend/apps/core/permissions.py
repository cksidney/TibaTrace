"""Server-side capability checks; UI visibility is never an authority gate."""
from rest_framework.permissions import BasePermission


class TenantRequired(BasePermission):
    message = "An active tenant is required."

    def has_permission(self, request, view):
        return bool(getattr(request, "tenant_id", None))


class CapabilityRequired(BasePermission):
    message = "The required capability is not assigned."

    def has_permission(self, request, view):
        capability = getattr(view, "required_capability", "")
        return bool(capability and request.user.has_capability(capability, tenant_id=request.tenant_id))


class TenantCapabilityPermission(BasePermission):
    message = "The required tenant capability is not assigned."

    def has_permission(self, request, view):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return False
        capability = (getattr(view, "write_capability", "") if request.method not in {"GET", "HEAD", "OPTIONS"}
                      else getattr(view, "read_capability", ""))
        capabilities = request.user.effective_capabilities(tenant_id=tenant_id)
        request.effective_capabilities = capabilities
        return bool(capability and ("*" in capabilities or capability in capabilities))


class CapabilityPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        required = getattr(view, "required_capabilities", ())
        tenant_id = getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
        return bool(required) and any(request.user.has_capability(cap, tenant_id=tenant_id) for cap in required)


class PlatformOwnerRequired(BasePermission):
    message = "Explicit platform authority is required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_platform_admin or user.is_superuser))


def require_tenant_capability(actor, tenant_id, *capabilities):
    """Require a named, active actor even for direct service calls."""
    from django.core.exceptions import PermissionDenied

    if not tenant_id or not actor or not actor.is_authenticated or not actor.is_active or not any(
        actor.has_capability(capability, tenant_id=tenant_id) for capability in capabilities
    ):
        raise PermissionDenied("The required tenant capability is not assigned.")
