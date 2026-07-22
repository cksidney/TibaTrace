import logging
from typing import Any, Dict, List, Optional

import fhir.resources.resource
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ConversionResult(BaseModel):
    domain_command: Optional[Any] = None
    domain_dto: Optional[Any] = None
    fhir_resource: Optional[fhir.resources.resource.Resource] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unsupported_elements: List[str] = Field(default_factory=list)
    resolved_references: Dict[str, Any] = Field(default_factory=dict)
    unresolved_references: List[str] = Field(default_factory=list)
    semantic_notes: List[str] = Field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_exception(self, public_message: str) -> None:
        logger.warning("FHIR conversion failed: %s", public_message)
        self.errors.append(public_message)

    def has_errors(self) -> bool:
        return bool(self.errors)


class BaseFHIRConverter:
    """
    Base contract for all FHIR converters.
    Converters must not save ORM records directly, bypass domain services,
    or silently discard unsupported fields.
    """
    resource_type: str = ""

    def to_fhir(self, domain_object: Any, context: Dict[str, Any]) -> ConversionResult:
        """
        Convert a domain object into a FHIR resource.
        """
        raise NotImplementedError

    def to_domain_command(self, resource: fhir.resources.resource.Resource, context: Dict[str, Any]) -> ConversionResult:
        """
        Convert an inbound FHIR resource into a domain command or DTO.
        """
        raise NotImplementedError

    def validate_mapping(self, resource: fhir.resources.resource.Resource, context: Dict[str, Any]) -> bool:
        """
        Validate that the resource elements map correctly to domain requirements.
        """
        return True

    def collect_references(self, resource: fhir.resources.resource.Resource, context: Dict[str, Any]) -> List[str]:
        """
        Collect all FHIR references that need to be resolved prior to mapping.
        """
        return []
