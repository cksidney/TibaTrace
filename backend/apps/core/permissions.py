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
        capability = (
            getattr(view, "write_capability", "")
            if request.method not in {"GET", "HEAD", "OPTIONS"}
            else getattr(view, "read_capability", "")
        )
        capabilities = request.user.effective_capabilities(tenant_id=tenant_id)
        request.effective_capabilities = capabilities
        return bool(
            capability
            and ("*" in capabilities or capability in capabilities)
        )
