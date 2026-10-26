from __future__ import annotations

import json
import re
import uuid

from django.core.exceptions import ValidationError
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
        # This single route authenticates DHA's provisioned callback bearer,
        # not an application JWT. Its view resolves tenant/facility from the
        # connection and rejects client-supplied scope and suspended tenants.
        if request.method == "POST" and re.fullmatch(
            r"/api/nif/dha/callbacks/[0-9a-f-]{36}/(claim|preauth|authorization)/", request.path
        ):
            request.tenant_id, request.tenant = None, None
            context = set_current_tenant_id(None)
            try:
                return self.get_response(request)
            finally:
                reset_current_tenant_id(context)
        # DRF authenticates after middleware. Resolve Bearer identity here too,
        # before accepting a workspace header or enforcing tenant lifecycle.
        # Never decode claims without signature/expiry/revocation validation.
        from rest_framework.exceptions import AuthenticationFailed

        from apps.identity.authentication import MfaJWTAuthentication

        try:
            authenticated = MfaJWTAuthentication().authenticate(request)
        except AuthenticationFailed:
            response = JsonResponse({"detail": "Invalid or expired authentication."}, status=401)
            response["WWW-Authenticate"] = 'Bearer realm="api"'
            return response
        if authenticated is not None:
            request.user, request.auth = authenticated
        # Resolve MFA before any tenant, admin or business workflow. An
        # authenticated password session is restricted until the second factor.
        if authenticated is None and getattr(request.user, 'is_authenticated', False):
            from apps.identity.mfa import session_status
            mfa_state = session_status(request)
            allowed = (request.path == '/api/identity/session/' or request.path.startswith('/api/identity/mfa/')
                       or request.path.startswith('/api/identity/token/')
                       or (request.path == '/api/identity/password/change/' and not mfa_state['enrolled'])
                       or request.path == '/admin/logout/')
            if mfa_state['required'] and not mfa_state['verified'] and not allowed:
                return JsonResponse({'detail': 'Complete MFA verification in HQ before continuing.',
                                     'code': 'mfa_required'}, status=403)
        header_tenant = str(request.headers.get("X-Tenant-ID") or "").strip()
        user = getattr(request, "user", None)
        user_tenant = str(getattr(user, "tenant_id", "") or "").strip()
        platform_authority = bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))
        if request.path.startswith("/api/nif/platform/") and not platform_authority:
            return JsonResponse({"detail": "Explicit platform authority is required."}, status=403)
        if header_tenant and getattr(user, "is_authenticated", False) and header_tenant != user_tenant and not platform_authority:
            return JsonResponse({"detail": "Requested tenant is outside the authenticated identity."}, status=403)

        request.tenant_id = header_tenant or user_tenant or None
        request.tenant = None
        if request.tenant_id:
            from apps.tenancy.models import Tenant

            try:
                request.tenant = Tenant.objects.get(pk=request.tenant_id)
            except (Tenant.DoesNotExist, ValueError, ValidationError):
                return JsonResponse({"detail": "Invalid workspace."}, status=403)

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

        password_routes = (
            "/api/identity/session/", "/api/identity/me/", "/api/identity/password/",
            "/api/identity/token/", "/api/health/",
            "/api/identity/mfa/",
        )
        if (
            getattr(user, "is_authenticated", False)
            and getattr(user, "must_change_password", False)
            and not any(request.path.startswith(prefix) for prefix in password_routes)
        ):
            return JsonResponse({"detail": "Change your temporary password before continuing.",
                                 "code": "password_change_required"}, status=403)

        token = set_current_tenant_id(request.tenant_id)
        try:
            refusal = self._refuse_unactivated_pos_mutation(request)
            if refusal is not None:
                return refusal
            return self.get_response(request)
        finally:
            reset_current_tenant_id(token)

    @staticmethod
    def _refuse_unactivated_pos_mutation(request):
        from django.conf import settings
        from django.core.exceptions import PermissionDenied

        protected = ("/api/pos/dispensing/", "/api/pos/payments/", "/api/pos/retail/", "/api/pos/clinical-screening/")
        if (request.method in {"GET", "HEAD", "OPTIONS"} or not request.path.startswith(protected)
                or not getattr(request.user, "is_authenticated", False) or request.tenant is None
                or request.tenant.is_demo or settings.DEBUG or getattr(settings, "TESTING", False)):
            return None
        from apps.platform.pos_activation import verify_device_credential

        try:
            device_id = request.headers.get("X-POS-Device-ID", "")
            record = verify_device_credential(tenant_id=request.tenant_id,
                credential=request.headers.get("X-POS-Activation", ""), device_id=device_id,
                fingerprint=request.headers.get("X-POS-Fingerprint", ""))
            if request.content_type == "application/json" and request.body:
                body = json.loads(request.body)
                if isinstance(body, dict) and body.get("device_id", device_id) != record.device_id:
                    raise PermissionDenied("Transaction device differs from its activation credential.")
        except (PermissionDenied, ValueError):
            return JsonResponse({"detail": "An approved, current device activation is required for POS operations.",
                                 "code": "pos_activation_required"}, status=403)
        request.pos_activation = record
        return None

    def _refuse_non_operational_tenant(self, request, user):
        if not request.tenant_id:
            return None
        if getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False):
            return None
        if any(request.path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return None

        from apps.tenancy.models import Tenant

        status = request.tenant.status if request.tenant is not None else None
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
