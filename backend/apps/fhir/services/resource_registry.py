from typing import Any, Dict, List, Literal, Union

from pydantic import BaseModel, Field, validator

FHIRSearchParamType = Literal[
    "number",
    "date",
    "string",
    "token",
    "reference",
    "composite",
    "quantity",
    "uri",
    "special",
]


class SearchParameterSpec(BaseModel):
    """CapabilityStatement search parameter with the correct FHIR type."""

    name: str
    type: FHIRSearchParamType = "string"


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
    search_parameters: List[Union[str, SearchParameterSpec]] = Field(default_factory=list)
    supported_profiles: List[str] = Field(default_factory=list)
    read_permission: str = ""
    write_permission: str = ""

    @validator("search_parameters", pre=True, each_item=True)
    def _coerce_search_param(cls, value):
        if isinstance(value, str):
            return SearchParameterSpec(name=value, type=_infer_search_type(value))
        if isinstance(value, dict):
            return SearchParameterSpec(**value)
        return value

    def search_parameter_specs(self) -> List[SearchParameterSpec]:
        specs: List[SearchParameterSpec] = []
        for row in self.search_parameters:
            if isinstance(row, SearchParameterSpec):
                specs.append(row)
            else:
                specs.append(SearchParameterSpec(name=str(row), type=_infer_search_type(str(row))))
        return specs

    def search_parameter_names(self) -> List[str]:
        return [row.name for row in self.search_parameter_specs()]


def _infer_search_type(name: str) -> FHIRSearchParamType:
    """Best-effort FHIR search types for common parameter names.

    Explicit SearchParameterSpec entries always win; this is the fallback when a
    registration still lists bare strings.
    """
    token_names = {
        "_id",
        "identifier",
        "active",
        "status",
        "code",
        "category",
        "gender",
        "type",
        "clinical-status",
        "verification-status",
    }
    reference_names = {
        "patient",
        "subject",
        "requester",
        "practitioner",
        "organization",
        "location",
        "encounter",
        "medication",
        "prescription",
        "context",
        "performer",
        "agent",
        "entity",
        "source",
        "destination",
    }
    date_names = {
        "birthdate",
        "date",
        "authoredon",
        "whenhandedover",
        "whenprepared",
        "onset-date",
        "recorded-date",
        "effective",
    }
    if name in token_names:
        return "token"
    if name in reference_names:
        return "reference"
    if name in date_names:
        return "date"
    if name in {"_count"}:
        return "number"
    return "string"


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
