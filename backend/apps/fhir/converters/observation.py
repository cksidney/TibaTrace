from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.observation import Observation
from fhir.resources.quantity import Quantity
from fhir.resources.reference import Reference

from apps.clinical.models import ClinicalObservation
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class ObservationConverter(BaseFHIRConverter):
    resource_type = "Observation"

    def to_fhir(self, domain_object: ClinicalObservation, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.status.lower().replace("_", "-")

            code = CodeableConcept(
                coding=[Coding(code=domain_object.code, system=domain_object.system, display=domain_object.display)]
            )

            observation = Observation(
                id=str(domain_object.id),
                status=status,
                code=code,
                subject=Reference(reference=f"Patient/{domain_object.patient_id}")
            )

            if domain_object.encounter_id:
                observation.encounter = Reference(reference=f"Encounter/{domain_object.encounter_id}")

            if domain_object.category:
                observation.category = [CodeableConcept(coding=[Coding(code=domain_object.category)])]

            if domain_object.effective_time:
                observation.effectiveDateTime = domain_object.effective_time.isoformat()

            if domain_object.value_quantity is not None and domain_object.value_unit:
                observation.valueQuantity = Quantity(
                    value=float(domain_object.value_quantity),
                    unit=domain_object.value_unit
                )
            elif domain_object.value_string:
                observation.valueString = domain_object.value_string

            if domain_object.interpretation:
                observation.interpretation = [CodeableConcept(coding=[Coding(code=domain_object.interpretation)])]

            result.fhir_resource = observation
        except Exception:
            result.add_exception("Clinical observation could not be rendered as Observation.")

        return result

    def to_domain_command(self, resource: Observation, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            status = resource.status.upper().replace("-", "_")

            encounter_id = None
            if resource.encounter and resource.encounter.reference:
                encounter_id = resource.encounter.reference.split("/")[-1]

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

            effective_time = resource.effectiveDateTime if hasattr(resource, "effectiveDateTime") and resource.effectiveDateTime else None

            value_quantity = None
            value_unit = None
            if resource.valueQuantity:
                value_quantity = resource.valueQuantity.value
                value_unit = resource.valueQuantity.unit

            value_string = None
            if resource.valueString:
                value_string = resource.valueString

            interpretation = None
            if resource.interpretation and len(resource.interpretation) > 0 and resource.interpretation[0].coding:
                interpretation = resource.interpretation[0].coding[0].code

            result.domain_command = {
                "resource_type": "Observation",
                "id": resource.id,
                "patient_id": patient_id,
                "status": status,
                "encounter_id": encounter_id,
                "category": category,
                "code": code,
                "system": system,
                "display": display,
                "effective_time": effective_time,
                "value_quantity": value_quantity,
                "value_unit": value_unit,
                "value_string": value_string,
                "interpretation": interpretation
            }
        except Exception:
            result.add_exception("Observation could not be mapped to a domain command.")

        return result
