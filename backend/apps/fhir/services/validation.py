import logging
import typing

from pydantic import ValidationError

from apps.fhir.constants import ISSUE_CODE_STRUCTURE, SEVERITY_ERROR
from apps.fhir.exceptions import FHIRValidationError

logger = logging.getLogger(__name__)

class FHIRValidationService:
    """Validates raw JSON dicts against fhir.resources Pydantic models."""

    @classmethod
    def validate_resource(cls, resource_dict: dict, resource_class: typing.Type) -> typing.Any:
        """
        Validates the dictionary against the given resource class.
        Returns the parsed resource instance or raises FHIRValidationError.
        """
        try:
            return resource_class.parse_obj(resource_dict)
        except ValidationError as exc:
            # We catch pydantic's ValidationError and re-raise our domain specific one
            # The view layer will handle converting this to an OperationOutcome
            logger.info(
                "FHIR payload structure validation failed; exception_type=%s",
                type(exc).__name__,
            )
            raise FHIRValidationError(
                message="FHIR payload structure validation failed.",
                severity=SEVERITY_ERROR,
                code=ISSUE_CODE_STRUCTURE,
                diagnostics="Payload does not conform to the declared FHIR R4 resource schema.",
            ) from exc
