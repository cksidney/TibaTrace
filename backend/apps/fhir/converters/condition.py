from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.condition import Condition
from fhir.resources.reference import Reference

from apps.clinical.models import ClinicalCondition
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class ConditionConverter(BaseFHIRConverter):
    resource_type = "Condition"

    def to_fhir(self, domain_object: ClinicalCondition, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            condition = Condition(
                id=str(domain_object.id),
                subject=Reference(reference=f"Patient/{domain_object.patient_id}"),
                clinicalStatus=CodeableConcept(coding=[Coding(system="http://terminology.hl7.org/CodeSystem/condition-clinical", code=domain_object.clinical_status.lower().replace("_", "-"))]),
                verificationStatus=CodeableConcept(coding=[Coding(system="http://terminology.hl7.org/CodeSystem/condition-ver-status", code=domain_object.verification_status.lower().replace("_", "-"))])
            )

            if domain_object.encounter_id:
                condition.encounter = Reference(reference=f"Encounter/{domain_object.encounter_id}")

            if domain_object.category:
                condition.category = [CodeableConcept(coding=[Coding(code=domain_object.category)])]

            if domain_object.code:
                condition.code = CodeableConcept(
                    coding=[Coding(code=domain_object.code, system=domain_object.system, display=domain_object.display)],
                    text=domain_object.display
                )

            if domain_object.onset_date:
                condition.onsetDateTime = domain_object.onset_date.isoformat()

            if domain_object.recorded_date:
                condition.recordedDate = domain_object.recorded_date.isoformat()

            result.fhir_resource = condition
        except Exception:
            result.add_exception("Clinical condition could not be rendered as Condition.")

        return result

    def to_domain_command(self, resource: Condition, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            encounter_id = resource.encounter.reference.split("/")[-1] if resource.encounter and resource.encounter.reference else None

            clinical_status = "ACTIVE"
            if resource.clinicalStatus and resource.clinicalStatus.coding:
                clinical_status = resource.clinicalStatus.coding[0].code.upper().replace("-", "_")

            verification_status = "UNCONFIRMED"
            if resource.verificationStatus and resource.verificationStatus.coding:
                verification_status = resource.verificationStatus.coding[0].code.upper().replace("-", "_")

            category = None
            if resource.category and len(resource.category) > 0 and resource.category[0].coding:
                category = resource.category[0].coding[0].code

            code = None
            system = None
            display = None
            if resource.code and resource.code.coding:
                code = resource.code.coding[0].code
                system = resource.code.coding[0].system
                display = resource.code.coding[0].display or resource.code.text

            onset_date = resource.onsetDateTime if resource.onsetDateTime else None

            result.domain_command = {
                "resource_type": "Condition",
                "id": resource.id,
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "clinical_status": clinical_status,
                "verification_status": verification_status,
                "category": category,
                "code": code,
                "system": system,
                "display": display,
                "onset_date": onset_date
            }
        except Exception:
            result.add_exception("Condition could not be mapped to a domain command.")

        return result
