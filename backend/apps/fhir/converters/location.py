from typing import Any, Dict

from fhir.resources.identifier import Identifier
from fhir.resources.location import Location as FHIRLocation
from fhir.resources.reference import Reference

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.organizations.models import Location


class LocationConverter(BaseFHIRConverter):
    resource_type = "Location"

    def to_fhir(self, domain_object: Location, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            identifiers = [Identifier(system=row.system, value=row.value) for row in domain_object.identifiers.all()]
            identifiers.insert(0, Identifier(system="https://dawatrace.health/fhir/system/location-code", value=domain_object.code))
            result.fhir_resource = FHIRLocation(
                id=str(domain_object.id),
                identifier=identifiers,
                status="active" if domain_object.status == "ACTIVE" else "inactive",
                name=domain_object.name,
                mode="instance",
                type=[{"text": domain_object.location_type}],
                managingOrganization=Reference(reference=f"Organization/{domain_object.organization_id}"),
            )
        except Exception:
            result.add_exception("Location could not be rendered as FHIR Location.")
        return result

    def to_domain_command(self, resource, context):
        result = ConversionResult()
        result.add_error("Location modification via FHIR is not supported in Phase 2.")
        return result
