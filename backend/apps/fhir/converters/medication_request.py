from typing import Any, Dict

import fhir.resources.dosage as fhir_dosage
import fhir.resources.identifier as fhir_id
import fhir.resources.medicationrequest as fhir_mr
import fhir.resources.quantity as fhir_qty
import fhir.resources.reference as fhir_ref

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.fhir.kenya_hie import patient_subject_reference
from apps.fhir.services.reference_resolver import FHIRReferenceResolver
from apps.prescription.models import PrescriptionItem


class MedicationRequestConverter(BaseFHIRConverter):
    resource_type = "MedicationRequest"

    def to_fhir(self, domain_object: PrescriptionItem, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()

        # In our mapping, MedicationRequest represents a PrescriptionItem.
        prescription = domain_object.prescription

        identifiers = [
            fhir_id.Identifier(
                system="https://mercato-os.com/fhir/system/prescription-item-id",
                value=str(domain_object.id)
            ),
            fhir_id.Identifier(
                system="https://mercato-os.com/fhir/system/prescription-id",
                value=str(prescription.id)
            )
        ]

        status_map = {
            'DRAFT': 'draft',
            'ISSUED': 'active',
            'VERIFIED': 'active',
            'DISPENSED_PARTIALLY': 'active',
            'DISPENSED': 'completed',
            'EXPIRED': 'stopped',
            'CANCELLED': 'cancelled',
            'REJECTED': 'cancelled',
            'SUSPENDED': 'on-hold',
            'COMPLETED': 'completed',
        }
        status = status_map.get(prescription.status, 'unknown')

        intent = "order" # Typically 'order' for prescriptions

        medication_ref = None
        if domain_object.canonical_medicine_id:
            medication_ref = fhir_ref.Reference(
                reference=f"Medication/{domain_object.canonical_medicine_id}",
                display=domain_object.medication_name
            )

        patient = getattr(prescription, "patient", None)
        subject = fhir_ref.Reference(
            reference=patient_subject_reference(patient, local_id=prescription.patient_id)
        )

        requester = fhir_ref.Reference(
            reference=f"Practitioner/{prescription.practitioner_id}"
        )

        dosage_inst = fhir_dosage.Dosage(
            text=domain_object.dosage_instruction
        )

        dispense_req = fhir_mr.MedicationRequestDispenseRequest(
            quantity=fhir_qty.Quantity(
                value=float(domain_object.quantity),
                unit="unit"
            ),
            numberOfRepeatsAllowed=domain_object.refills_authorized
        )

        mr = fhir_mr.MedicationRequest(
            id=str(domain_object.id),
            identifier=identifiers,
            status=status,
            intent=intent,
            medicationReference=medication_ref,
            subject=subject,
            requester=requester,
            authoredOn=prescription.issued_at.isoformat() if prescription.issued_at else None,
            dosageInstruction=[dosage_inst],
            dispenseRequest=dispense_req
        )

        result.fhir_resource = mr
        return result

    def to_domain_command(self, resource: fhir_mr.MedicationRequest, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        tenant_id = context.get('tenant_id')
        bundle_context = context.get('bundle_context', {})

        try:
            # Resolve references
            patient = FHIRReferenceResolver.resolve(
                resource.subject.reference, "Patient", tenant_id, bundle_context
            )
            practitioner = FHIRReferenceResolver.resolve(
                resource.requester.reference, "Practitioner", tenant_id, bundle_context
            )

            medication_id = None
            medication_name = "Unknown Medication"
            if resource.medicationReference:
                med = FHIRReferenceResolver.resolve(
                    resource.medicationReference.reference, "Medication", tenant_id, bundle_context
                )
                medication_id = med.id if med else None
                medication_name = resource.medicationReference.display or "Mapped Medication"
            elif resource.medicationCodeableConcept:
                medication_name = resource.medicationCodeableConcept.text or "CodeableConcept Medication"

            qty = 1.0
            refills = 0
            if resource.dispenseRequest:
                if resource.dispenseRequest.quantity and resource.dispenseRequest.quantity.value:
                    qty = float(resource.dispenseRequest.quantity.value)
                if resource.dispenseRequest.numberOfRepeatsAllowed:
                    refills = resource.dispenseRequest.numberOfRepeatsAllowed

            dosage = "As directed"
            if resource.dosageInstruction and len(resource.dosageInstruction) > 0:
                dosage = resource.dosageInstruction[0].text or dosage

            # Construct a domain DTO/command
            domain_command = {
                "id": resource.id,
                "patient_id": patient.id if patient else None,
                "practitioner_id": practitioner.id if practitioner else None,
                "items": [
                    {
                        "medication_id": medication_id,
                        "medication_name": medication_name,
                        "quantity": qty,
                        "refills_authorized": refills,
                        "dosage_instruction": dosage
                    }
                ],
                "identifier": resource.identifier[0].value if resource.identifier else None
            }

            result.domain_command = domain_command

        except Exception:
            result.add_exception("MedicationRequest could not be mapped to a domain command.")

        return result
