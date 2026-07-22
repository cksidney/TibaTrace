import logging

import fhir.resources.bundle as fhir_bundle
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.api.bundle_processor import BundleProcessor
from apps.fhir.exceptions import FHIRSecurityError, FHIRValidationError

logger = logging.getLogger(__name__)

class BundleView(BaseFHIRAPIView):
    """
    Handles FHIR POST to the root endpoint (Batch/Transaction processing).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise FHIRSecurityError("Missing tenant context.")
        if not settings.FHIR_WRITE_INTERACTIONS_ENABLED:
            raise FHIRValidationError(
                "FHIR Bundle writes are disabled until the production certification gate passes.",
                code="not-supported",
            )

        payload = request.data
        if payload.get("resourceType") != "Bundle":
            raise FHIRValidationError(
                message="Expected resourceType Bundle",
                diagnostics=f"Received {payload.get('resourceType')}"
            )

        try:
            bundle = fhir_bundle.Bundle.parse_obj(payload)
        except Exception as exc:
            logger.warning(
                "FHIR Bundle parsing failed; exception_type=%s",
                type(exc).__name__,
            )
            raise FHIRValidationError(
                message="Bundle validation failed.",
                diagnostics="Payload does not conform to the declared FHIR R4 Bundle schema.",
            )

        if len(bundle.entry or []) > settings.FHIR_BUNDLE_MAX_ENTRIES:
            raise FHIRValidationError(
                "FHIR Bundle exceeds the configured entry limit.",
                diagnostics=f"Maximum entries: {settings.FHIR_BUNDLE_MAX_ENTRIES}",
            )

        response_bundle = BundleProcessor.process(bundle, tenant_id, request.user)

        return Response(response_bundle.dict(exclude_none=True), status=200)
