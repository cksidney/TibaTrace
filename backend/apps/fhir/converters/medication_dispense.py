from typing import Any, Dict

import fhir.resources.identifier as fhir_id
import fhir.resources.medicationdispense as fhir_md
import fhir.resources.quantity as fhir_qty
import fhir.resources.reference as fhir_ref

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.fhir.kenya_hie import patient_subject_reference
from apps.fhir.services.reference_resolver import FHIRReferenceResolver
from apps.prescription.models import PrescriptionFill


class MedicationDispenseConverter(BaseFHIRConverter):
    resource_type = "MedicationDispense"

    def to_fhir(self, domain_object: PrescriptionFill, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()

        dispense = domain_object.dispense
        prescription = domain_object.item.prescription

        identifiers = [
            fhir_id.Identifier(
                system="https://mercato-os.com/fhir/system/prescription-fill-id",
                value=str(domain_object.id)
            ),
            fhir_id.Identifier(
                system="https://mercato-os.com/fhir/system/prescription-dispense-id",
                value=str(dispense.id)
            )
        ]

        status_map = {
            'COMPLETED': 'completed',
            'CANCELLED': 'cancelled',
            'REJECTED': 'declined',
        }
        status = status_map.get(dispense.status, 'unknown')

        medication_id = domain_object.substituted_medicine_id or domain_object.item.canonical_medicine_id
        medication_ref = None
        if medication_id:
            medication_ref = fhir_ref.Reference(
                reference=f"Medication/{medication_id}"
            )

        patient = getattr(prescription, "patient", None)
        subject = fhir_ref.Reference(
            reference=patient_subject_reference(patient, local_id=prescription.patient_id)
        )

        authorizing_prescription = [
            fhir_ref.Reference(
                reference=f"MedicationRequest/{domain_object.item_id}"
            )
        ]

        qty = fhir_qty.Quantity(
            value=float(domain_object.quantity_dispensed),
            unit="unit"
        )

        md = fhir_md.MedicationDispense(
            id=str(domain_object.id),
            identifier=identifiers,
            status=status,
            medicationReference=medication_ref,
            subject=subject,
            authorizingPrescription=authorizing_prescription,
            quantity=qty,
            whenHandedOver=dispense.dispensed_at.isoformat() if dispense.dispensed_at else None
        )

        # Link to Location (Store/Facility)
        if dispense.location_id:
            md.location = fhir_ref.Reference(
                reference=f"Location/{dispense.location_id}"
            )

        result.fhir_resource = md
        return result

    def to_domain_command(self, resource: fhir_md.MedicationDispense, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        tenant_id = context.get('tenant_id')
        bundle_context = context.get('bundle_context', {})

        try:
            # Resolve references
            patient = None
            if resource.subject:
                patient = FHIRReferenceResolver.resolve(
                    resource.subject.reference, "Patient", tenant_id, bundle_context
                )

            medication_id = None
            if resource.medicationReference:
                med = FHIRReferenceResolver.resolve(
                    resource.medicationReference.reference, "Medication", tenant_id, bundle_context
                )
                medication_id = med.id if med else None

            qty = 1.0
            if resource.quantity and resource.quantity.value:
                qty = float(resource.quantity.value)

            domain_command = {
                "patient_id": patient.id if patient else None,
                "medication_id": medication_id,
                "quantity_dispensed": qty,
                "identifier": resource.identifier[0].value if resource.identifier else None,
                "prescription_item_id": (
                    resource.authorizingPrescription[0].reference.split("/")[-1]
                    if resource.authorizingPrescription and resource.authorizingPrescription[0].reference
                    else None
                ),
            }

            result.domain_command = domain_command

        except Exception:
            result.add_exception("MedicationDispense could not be mapped to a domain command.")

        return result
