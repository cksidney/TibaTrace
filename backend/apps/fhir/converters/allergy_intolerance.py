from typing import Any, Dict

from fhir.resources.allergyintolerance import AllergyIntolerance
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.reference import Reference

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.patients.models import PatientAllergy


class AllergyIntoleranceConverter(BaseFHIRConverter):
    resource_type = "AllergyIntolerance"

    def to_fhir(self, domain_object: PatientAllergy, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            fhir_status = "active" if domain_object.is_active else "inactive"

            # Map severity
            criticality = "low"
            if domain_object.severity == PatientAllergy.SEVERITY_WARNING:
                criticality = "high"
            elif domain_object.severity == PatientAllergy.SEVERITY_HARD_STOP:
                criticality = "unable-to-assess" # closest match or high

            code = CodeableConcept(
                text=domain_object.allergen_name,
                coding=[Coding(display=domain_object.allergen_name)]
            )

            allergy = AllergyIntolerance(
                id=str(domain_object.id),
                clinicalStatus=CodeableConcept(coding=[Coding(system="http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", code=fhir_status)]),
                code=code,
                patient=Reference(reference=f"Patient/{domain_object.patient_id}"),
                criticality=criticality
            )

            if domain_object.reaction:
                allergy.reaction = [{"manifestation": [CodeableConcept(text=domain_object.reaction)]}]

            if domain_object.notes:
                allergy.note = [{"text": domain_object.notes}]

            result.fhir_resource = allergy
        except Exception:
            result.add_exception("Patient allergy could not be rendered as AllergyIntolerance.")

        return result

    def to_domain_command(self, resource: AllergyIntolerance, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.patient.reference.split("/")[-1] if resource.patient and resource.patient.reference else None
            if not patient_id:
                result.add_error("Patient reference is required.")
                return result

            allergen_name = resource.code.text if resource.code and resource.code.text else ""
            if not allergen_name and resource.code and resource.code.coding:
                allergen_name = resource.code.coding[0].display or resource.code.coding[0].code

            severity = PatientAllergy.SEVERITY_INFO
            if resource.criticality == "high":
                severity = PatientAllergy.SEVERITY_WARNING
            elif resource.criticality == "unable-to-assess":
                severity = PatientAllergy.SEVERITY_HARD_STOP

            is_active = True
            if resource.clinicalStatus and resource.clinicalStatus.coding:
                status_code = resource.clinicalStatus.coding[0].code
                if status_code in ["inactive", "resolved"]:
                    is_active = False

            reaction_text = ""
            if resource.reaction and len(resource.reaction) > 0 and resource.reaction[0].manifestation:
                manifestation = resource.reaction[0].manifestation[0]
                reaction_text = manifestation.text or (manifestation.coding[0].display if manifestation.coding else "")

            notes = ""
            if resource.note and len(resource.note) > 0:
                notes = resource.note[0].text

            result.domain_command = {
                "resource_type": "PatientAllergy",
                "id": resource.id,
                "patient_id": patient_id,
                "allergen_name": allergen_name,
                "severity": severity,
                "is_active": is_active,
                "reaction": reaction_text,
                "notes": notes
            }
        except Exception:
            result.add_exception("AllergyIntolerance could not be mapped to a domain command.")

        return result
