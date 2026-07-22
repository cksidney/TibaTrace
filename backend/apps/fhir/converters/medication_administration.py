from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.medicationadministration import MedicationAdministration
from fhir.resources.reference import Reference

from apps.clinical.models import MedicationAdministrationRecord
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class MedicationAdministrationConverter(BaseFHIRConverter):
    resource_type = "MedicationAdministration"

    def to_fhir(self, domain_object: MedicationAdministrationRecord, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.status.lower().replace("_", "-")

            med_admin = MedicationAdministration(
                id=str(domain_object.id),
                status=status,
                subject=Reference(reference=f"Patient/{domain_object.patient_id}"),
                medicationCodeableConcept=CodeableConcept(text=domain_object.medication_name),
                effectiveDateTime=(
                    domain_object.effective_time.isoformat()
                    if domain_object.effective_time
                    else None
                ),
            )

            if domain_object.encounter_id:
                med_admin.context = Reference(reference=f"Encounter/{domain_object.encounter_id}")

            if domain_object.dosage_text:
                med_admin.dosage = {"text": domain_object.dosage_text}

            if domain_object.performer_id:
                med_admin.performer = [{"actor": Reference(reference=f"Practitioner/{domain_object.performer_id}")}]

            if domain_object.reason_not_done:
                med_admin.statusReason = [CodeableConcept(text=domain_object.reason_not_done)]

            result.fhir_resource = med_admin
        except Exception:
            result.add_exception("Administration record could not be rendered as MedicationAdministration.")

        return result

    def to_domain_command(self, resource: MedicationAdministration, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            status = resource.status.upper().replace("-", "_")

            medication_name = "Unknown Medication"
            if resource.medicationCodeableConcept and resource.medicationCodeableConcept.text:
                medication_name = resource.medicationCodeableConcept.text
            elif resource.medicationReference and resource.medicationReference.display:
                medication_name = resource.medicationReference.display

            encounter_id = None
            if resource.context and resource.context.reference:
                encounter_id = resource.context.reference.split("/")[-1]

            effective_time = resource.effectiveDateTime if hasattr(resource, "effectiveDateTime") and resource.effectiveDateTime else None

            dosage_text = None
            if resource.dosage and resource.dosage.text:
                dosage_text = resource.dosage.text

            performer_id = None
            if resource.performer and len(resource.performer) > 0 and resource.performer[0].actor and resource.performer[0].actor.reference:
                performer_id = resource.performer[0].actor.reference.split("/")[-1]

            reason_not_done = None
            if resource.statusReason and len(resource.statusReason) > 0 and resource.statusReason[0].text:
                reason_not_done = resource.statusReason[0].text

            result.domain_command = {
                "resource_type": "MedicationAdministration",
                "id": resource.id,
                "patient_id": patient_id,
                "status": status,
                "medication_name": medication_name,
                "encounter_id": encounter_id,
                "effective_time": effective_time,
                "dosage_text": dosage_text,
                "performer_id": performer_id,
                "reason_not_done": reason_not_done
            }
        except Exception:
            result.add_exception("MedicationAdministration could not be mapped to a domain command.")

        return result
