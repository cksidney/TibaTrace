from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.reference import Reference

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.patients.models import PatientMedication


class MedicationStatementConverter(BaseFHIRConverter):
    resource_type = "MedicationStatement"

    def to_fhir(self, domain_object: PatientMedication, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            kwargs = {
                "id": str(domain_object.id),
                "status": domain_object.status.lower(),
                "subject": Reference(reference=f"Patient/{domain_object.patient_id}"),
                "dosage": [{"text": domain_object.directions}] if domain_object.directions else None,
            }
            if domain_object.medicine_id:
                kwargs["medicationReference"] = Reference(reference=f"Medication/{domain_object.medicine_id}")
            else:
                kwargs["medicationCodeableConcept"] = CodeableConcept(text=domain_object.medication_name)
            if domain_object.effective_start or domain_object.effective_end:
                kwargs["effectivePeriod"] = {
                    "start": domain_object.effective_start,
                    "end": domain_object.effective_end,
                }
            result.fhir_resource = MedicationStatement(**kwargs)
        except Exception:
            result.add_exception("Medication profile could not be rendered as MedicationStatement.")
        return result

    def to_domain_command(self, resource: MedicationStatement, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result
            medicine_id = None
            medication_name = "Medication"
            if resource.medicationReference and resource.medicationReference.reference:
                medicine_id = resource.medicationReference.reference.split("/")[-1]
                medication_name = resource.medicationReference.display or medication_name
            elif resource.medicationCodeableConcept:
                medication_name = resource.medicationCodeableConcept.text or medication_name
            result.domain_command = {
                "id": resource.id,
                "patient_id": patient_id,
                "status": (resource.status or "active").upper(),
                "medicine_id": medicine_id,
                "medication_name": medication_name,
                "directions": resource.dosage[0].text if resource.dosage else "",
            }
        except Exception:
            result.add_exception("MedicationStatement could not be mapped to a domain command.")
        return result
