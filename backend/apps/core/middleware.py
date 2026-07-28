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

        # Suspension has to mean something.
        #
        # A tenant's status was decorative until now: suspending a pharmacy set a
        # column and a JSON key, and that pharmacy carried on signing in and
        # reading the API exactly as before. A "Suspend" button that stops
        # nothing is worse than none, because it reports an action that did not
        # happen.
        #
        # Platform administrators are exempt: somebody has to be able to look at
        # a suspended pharmacy in order to reinstate it.
        refusal = self._refuse_non_operational_tenant(request, user)
        if refusal is not None:
            return refusal

        token = set_current_tenant_id(request.tenant_id)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant_id(token)

    def _refuse_non_operational_tenant(self, request, user):
        if not request.tenant_id:
            return None
        if getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False):
            return None
        if any(request.path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return None

        from apps.tenancy.models import Tenant

        status = (
            Tenant.objects.filter(pk=request.tenant_id)
            .values_list("status", flat=True)
            .first()
        )
        # An unknown tenant id is not this check's business; the request will
        # fail on its own terms further in.
        if status is None or status in Tenant.OPERATIONAL_STATUSES:
            return None

        # The state is named so an operator can tell "we have not gone live yet"
        # from "we have been stopped", which need different phone calls.
        return JsonResponse(
            {
                "detail": "This pharmacy is not currently active on the platform.",
                "tenant_status": status,
            },
            status=403,
        )
