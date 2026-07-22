from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.practitionerrole import PractitionerRole as FHIRPractitionerRole
from fhir.resources.reference import Reference

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.practitioners.models import PractitionerRole


class PractitionerRoleConverter(BaseFHIRConverter):
    resource_type = "PractitionerRole"

    def to_fhir(self, domain_object: PractitionerRole, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            result.fhir_resource = FHIRPractitionerRole(
                id=str(domain_object.id),
                active=domain_object.status == "ACTIVE",
                practitioner=Reference(reference=f"Practitioner/{domain_object.practitioner_id}"),
                organization=Reference(reference=f"Organization/{domain_object.organization_id}"),
                location=[Reference(reference=f"Location/{domain_object.location_id}")] if domain_object.location_id else None,
                code=[CodeableConcept(coding=[Coding(code=domain_object.role_code)])],
                specialty=[CodeableConcept(coding=[Coding(code=domain_object.specialty_code)])] if domain_object.specialty_code else None,
            )
        except Exception:
            result.add_exception("Practitioner role could not be rendered as FHIR PractitionerRole.")
        return result

    def to_domain_command(self, resource, context):
        result = ConversionResult()
        result.add_error("PractitionerRole modification via FHIR is not supported in Phase 2.")
        return result
