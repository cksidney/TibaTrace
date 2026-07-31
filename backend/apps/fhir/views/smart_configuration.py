"""SMART on FHIR discovery for the Kenya ePrescription exchange surface."""
from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.kenya_ig import SMART_SCOPES_DECLARED


class SmartConfigurationView(BaseFHIRAPIView):
    """`.well-known/smart-configuration` (SMART App Launch).

    Authorization and token endpoints are configured via settings. Wire AfyaLink /
    Kenya HIE IdP endpoints via DAWATRACE_FHIR_SMART_* (Bearer JWT). Until wired,
    discovery still advertises intended scopes for CapStmt consumers.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        base = settings.FHIR_PUBLIC_BASE_URL
        if request:
            base = request.build_absolute_uri("/api/fhir/r4/")
        if not base.endswith("/"):
            base += "/"

        authorize = getattr(settings, "FHIR_SMART_AUTHORIZATION_ENDPOINT", "") or ""
        token = getattr(settings, "FHIR_SMART_TOKEN_ENDPOINT", "") or ""
        registration = getattr(settings, "FHIR_SMART_REGISTRATION_ENDPOINT", "") or ""
        management = getattr(settings, "FHIR_SMART_MANAGEMENT_ENDPOINT", "") or ""
        introspection = getattr(settings, "FHIR_SMART_INTROSPECTION_ENDPOINT", "") or ""
        revocation = getattr(settings, "FHIR_SMART_REVOCATION_ENDPOINT", "") or ""
        afyalink = getattr(settings, "FHIR_AFYALINK_TOKEN_URL", "") or ""

        payload = {
            "issuer": getattr(settings, "FHIR_SMART_ISSUER", "") or base.rstrip("/"),
            "jwks_uri": getattr(settings, "FHIR_SMART_JWKS_URI", "") or None,
            "authorization_endpoint": authorize or None,
            "token_endpoint": token or afyalink or None,
            "registration_endpoint": registration or None,
            "management_endpoint": management or None,
            "introspection_endpoint": introspection or None,
            "revocation_endpoint": revocation or None,
            "grant_types_supported": ["authorization_code", "client_credentials", "refresh_token"],
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "private_key_jwt",
            ],
            "scopes_supported": list(SMART_SCOPES_DECLARED),
            "capabilities": [
                "launch-ehr",
                "launch-standalone",
                "client-public",
                "client-confidential-symmetric",
                "client-confidential-asymmetric",
                "sso-openid-connect",
                "context-banner",
                "context-style",
                "context-ehr-patient",
                "context-standalone-patient",
                "permission-offline",
                "permission-patient",
                "permission-user",
            ],
        }
        # Drop nulls for cleaner discovery documents.
        return Response({k: v for k, v in payload.items() if v is not None})
