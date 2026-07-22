from typing import Any, Dict

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.identifier import Identifier
from fhir.resources.medication import Medication as FHIRMedication

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.medicines.models import Medicine


class MedicationConverter(BaseFHIRConverter):
    resource_type = "Medication"

    def to_fhir(self, domain_object: Medicine, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            identifiers = [Identifier(system=row.system, value=row.value) for row in domain_object.identifiers.all()]
            if domain_object.primary_barcode:
                identifiers.append(Identifier(system="https://dawatrace.health/fhir/system/barcode", value=domain_object.primary_barcode))
            result.fhir_resource = FHIRMedication(
                id=str(domain_object.id),
                identifier=identifiers or None,
                status="active" if domain_object.status == Medicine.STATUS_ACTIVE else "inactive",
                code=CodeableConcept(
                    coding=[Coding(system="https://dawatrace.health/fhir/system/medicine", code=domain_object.code)],
                    text=domain_object.brand_name or domain_object.generic_name,
                ),
                form=CodeableConcept(text=domain_object.dosage_form) if domain_object.dosage_form else None,
            )
        except Exception:
            result.add_exception("Medicine could not be rendered as FHIR Medication.")
        return result

    def to_domain_command(self, resource, context):
        result = ConversionResult()
        result.add_error("Medication modification via FHIR is not supported in Phase 2.")
        return result
