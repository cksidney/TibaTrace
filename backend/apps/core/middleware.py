from __future__ import annotations

import uuid

from django.http import JsonResponse

from apps.core.request_context import reset_current_request_id, set_current_request_id
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id


class CorrelationIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(request.headers.get("X-Request-ID") or uuid.uuid4())
        token = set_current_request_id(request.request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request.request_id
            return response
        finally:
            reset_current_request_id(token)


class TenantContextMiddleware:
    EXEMPT_PREFIXES = (
        "/api/health/",
        "/api/schema/",
        "/api/docs/",
        "/admin/",
        "/admin-shell/",
        "/api/identity/token/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header_tenant = str(request.headers.get("X-Tenant-ID") or "").strip()
        user = getattr(request, "user", None)
        user_tenant = str(getattr(user, "tenant_id", "") or "").strip()
        if header_tenant and user_tenant and header_tenant != user_tenant and not getattr(user, "is_platform_admin", False):
            return JsonResponse({"detail": "Requested tenant is outside the authenticated identity."}, status=403)

        request.tenant_id = header_tenant or user_tenant or None
        token = set_current_tenant_id(request.tenant_id)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant_id(token)
