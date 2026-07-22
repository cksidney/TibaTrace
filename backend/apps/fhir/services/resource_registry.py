from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ResourceInteraction(BaseModel):
    create: bool = False
    update: bool = False
    read: bool = False
    search: bool = False

class ResourceRegistration(BaseModel):
    resource_type: str
    converter_class: Any
    service_class: Any
    interactions: ResourceInteraction
    search_parameters: List[str] = Field(default_factory=list)
    supported_profiles: List[str] = Field(default_factory=list)
    read_permission: str = ""
    write_permission: str = ""


class FHIRResourceRegistry:
    """Central registry for supported FHIR resources and interactions."""

    _registry: Dict[str, ResourceRegistration] = {}

    @classmethod
    def register(cls, registration: ResourceRegistration):
        """Register a FHIR resource."""
        cls._registry[registration.resource_type] = registration

    @classmethod
    def get_registration(cls, resource_type: str) -> ResourceRegistration:
        """Get registration for a resource type."""
        from apps.fhir.constants import ISSUE_CODE_NOT_SUPPORTED, SEVERITY_ERROR
        from apps.fhir.exceptions import FHIRNotSupportedError

        reg = cls._registry.get(resource_type)
        if not reg:
            raise FHIRNotSupportedError(
                f"Resource type '{resource_type}' is not supported.",
                severity=SEVERITY_ERROR,
                code=ISSUE_CODE_NOT_SUPPORTED
            )
        return reg

    @classmethod
    def all_registrations(cls) -> List[ResourceRegistration]:
        return list(cls._registry.values())

    @classmethod
    def is_supported(cls, resource_type: str) -> bool:
        return resource_type in cls._registry

# Singleton instance for easy access if needed
registry = FHIRResourceRegistry
