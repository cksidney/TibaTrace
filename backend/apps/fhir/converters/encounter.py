from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.encounter import Encounter
from fhir.resources.period import Period
from fhir.resources.reference import Reference

from apps.clinical.models import ClinicalEncounter
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class EncounterConverter(BaseFHIRConverter):
    resource_type = "Encounter"

    def to_fhir(self, domain_object: ClinicalEncounter, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.status.lower().replace("_", "-")

            encounter_class_coding = Coding(
                system="http://terminology.hl7.org/CodeSystem/v3-ActCode",
                code=domain_object.encounter_class,
            )
            encounter = Encounter(
                id=str(domain_object.id),
                status=status,
                subject=Reference(reference=f"Patient/{domain_object.patient_id}"),
                class_fhir=encounter_class_coding,
            )

            if domain_object.reason_code:
                encounter.reasonCode = [CodeableConcept(coding=[Coding(code=domain_object.reason_code)])]

            if domain_object.start_time or domain_object.end_time:
                period = Period()
                if domain_object.start_time:
                    period.start = domain_object.start_time.isoformat()
                if domain_object.end_time:
                    period.end = domain_object.end_time.isoformat()
                encounter.period = period

            if domain_object.organization_id:
                encounter.serviceProvider = Reference(reference=f"Organization/{domain_object.organization_id}")

            if domain_object.practitioner_id:
                encounter.participant = [{"individual": Reference(reference=f"Practitioner/{domain_object.practitioner_id}")}]

            result.fhir_resource = encounter
        except Exception:
            result.add_exception("Clinical encounter could not be rendered as Encounter.")

        return result

    def to_domain_command(self, resource: Encounter, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            status = resource.status.upper().replace("-", "_")

            encounter_class = None
            if resource.class_fhir:
                encounter_class = resource.class_fhir.code

            start_time = None
            end_time = None
            if resource.period:
                start_time = resource.period.start
                end_time = resource.period.end

            reason_code = None
            if resource.reasonCode and len(resource.reasonCode) > 0 and resource.reasonCode[0].coding:
                reason_code = resource.reasonCode[0].coding[0].code

            organization_id = None
            if resource.serviceProvider and resource.serviceProvider.reference:
                organization_id = resource.serviceProvider.reference.split("/")[-1]

            practitioner_id = None
            if resource.participant and len(resource.participant) > 0 and resource.participant[0].individual and resource.participant[0].individual.reference:
                practitioner_id = resource.participant[0].individual.reference.split("/")[-1]

            result.domain_command = {
                "resource_type": "Encounter",
                "id": resource.id,
                "patient_id": patient_id,
                "status": status,
                "encounter_class": encounter_class,
                "start_time": start_time,
                "end_time": end_time,
                "reason_code": reason_code,
                "organization_id": organization_id,
                "practitioner_id": practitioner_id
            }
        except Exception:
            result.add_exception("Encounter could not be mapped to a domain command.")

        return result
