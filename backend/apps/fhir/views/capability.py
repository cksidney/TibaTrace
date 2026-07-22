from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.fhir.api.base import BaseFHIRAPIView
from apps.fhir.services.capability_statement import CapabilityStatementService


class CapabilityStatementView(BaseFHIRAPIView):
    """
    Exposes the system's FHIR capabilities based on the active ResourceRegistry.
    """
    # No specific resource type constraint since this applies to the whole API
    fhir_resource_type = None
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        statement = CapabilityStatementService.generate(request)
        return Response(statement.dict(exclude_none=True))
