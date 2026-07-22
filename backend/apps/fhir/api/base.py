from drf_spectacular.utils import extend_schema
from pydantic import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fhir.exceptions import FHIRException
from apps.fhir.services.operation_outcome import OperationOutcomeFactory


@extend_schema(exclude=True)
class BaseFHIRAPIView(APIView):
    """
    Base view for all FHIR API endpoints.
    Automatically handles formatting exceptions into FHIR OperationOutcome responses.
    """

    # All FHIR views should define their primary resource type
    fhir_resource_type = None

    def handle_exception(self, exc):
        if isinstance(exc, FHIRException):
            outcome = OperationOutcomeFactory.from_exception(exc)
            # Default to 400 Bad Request for most FHIR business/validation rules
            status_code = status.HTTP_400_BAD_REQUEST
            if exc.code == "forbidden":
                status_code = status.HTTP_403_FORBIDDEN
            elif exc.code == "not-found":
                status_code = status.HTTP_404_NOT_FOUND
            elif exc.code == "conflict":
                status_code = status.HTTP_409_CONFLICT

            return Response(outcome.dict(exclude_none=True), status=status_code)

        elif isinstance(exc, ValidationError):
            outcome = OperationOutcomeFactory.from_pydantic_validation_error(exc)
            return Response(outcome.dict(exclude_none=True), status=status.HTTP_400_BAD_REQUEST)

        return super().handle_exception(exc)
