from typing import Any, Dict

from fhir.resources.contactpoint import ContactPoint
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.practitioner import Practitioner as FHIRPractitioner

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.practitioners.models import Practitioner


class PractitionerConverter(BaseFHIRConverter):
    resource_type = "Practitioner"

    def to_fhir(self, domain_object: Practitioner, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            telecom = []
            if domain_object.phone:
                telecom.append(ContactPoint(system="phone", value=domain_object.phone))
            if domain_object.email:
                telecom.append(ContactPoint(system="email", value=domain_object.email))
            identifiers = [Identifier(system=row.system, value=row.value) for row in domain_object.identifiers.all()]
            identifiers.extend(
                Identifier(
                    system="https://dawatrace.health/fhir/system/practitioner-licence",
                    value=licence.licence_number,
                )
                for licence in domain_object.licences.filter(status="VALID")
            )
            result.fhir_resource = FHIRPractitioner(
                id=str(domain_object.id),
                identifier=identifiers or None,
                active=domain_object.status == "ACTIVE",
                name=[HumanName(family=domain_object.last_name, given=[domain_object.first_name], text=domain_object.full_name)],
                telecom=telecom or None,
            )
        except Exception:
            result.add_exception("Practitioner could not be rendered as FHIR Practitioner.")
        return result

    def to_domain_command(self, resource, context):
        result = ConversionResult()
        result.add_error("Practitioner modification via FHIR is not supported in Phase 2.")
        return result
