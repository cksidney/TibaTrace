from typing import Any, Dict

from fhir.resources.identifier import Identifier
from fhir.resources.organization import Organization as FHIROrganization

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.organizations.models import Organization


class OrganizationConverter(BaseFHIRConverter):
    resource_type = "Organization"

    def to_fhir(self, domain_object: Organization, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            identifiers = [Identifier(system=row.system, value=row.value) for row in domain_object.identifiers.all()]
            identifiers.insert(0, Identifier(system="https://dawatrace.health/fhir/system/organization-code", value=domain_object.code))
            result.fhir_resource = FHIROrganization(
                id=str(domain_object.id),
                identifier=identifiers,
                active=domain_object.status == "ACTIVE",
                name=domain_object.name,
                type=[{"text": domain_object.organization_type}],
            )
        except Exception:
            result.add_exception("Organization could not be rendered as FHIR Organization.")
        return result

    def to_domain_command(self, resource, context):
        result = ConversionResult()
        result.add_error("Organization modification via FHIR is not supported in Phase 2.")
        return result
