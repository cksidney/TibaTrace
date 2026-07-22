import uuid
from typing import Optional

from django.db import transaction

from apps.fhir.services.search_utils import bounded_count, reference_id
from apps.practitioners.models import PractitionerRole
from apps.prescription.models import Prescription, PrescriptionItem


class MedicationRequestLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[PrescriptionItem]:
        return PrescriptionItem.all_objects.filter(
            id=resource_id,
            tenant_id=tenant_id,
            prescription__tenant_id=tenant_id,
        ).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = PrescriptionItem.all_objects.filter(tenant_id=tenant_id).select_related("prescription")
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("identifier"):
            queryset = queryset.filter(prescription__prescription_number=str(params["identifier"]).split("|")[-1])
        if params.get("subject"):
            queryset = queryset.filter(prescription__patient_id=reference_id(params["subject"], "Patient"))
        if params.get("requester"):
            queryset = queryset.filter(prescription__practitioner_id=reference_id(params["requester"], "Practitioner"))
        if params.get("status"):
            status_map = {"draft": "DRAFT", "active": "ISSUED", "completed": "DISPENSED", "cancelled": "CANCELLED"}
            queryset = queryset.filter(prescription__status=status_map.get(str(params["status"]).lower(), "__NO_MATCH__"))
        if params.get("medication"):
            queryset = queryset.filter(canonical_medicine_id=reference_id(params["medication"], "Medication"))
        return list(queryset.order_by("-created_at")[: bounded_count(params)])

    @staticmethod
    @transaction.atomic
    def process_domain_command(domain_command: dict, context: dict) -> PrescriptionItem:
        tenant_id = context.get("tenant_id")
        if not tenant_id:
            raise ValueError("Tenant ID is missing in context.")
        patient_id = domain_command.get("patient_id")
        practitioner_id = domain_command.get("practitioner_id")
        role = PractitionerRole.all_objects.select_related("organization", "location").filter(
            tenant_id=tenant_id,
            practitioner_id=practitioner_id,
            status="ACTIVE",
            location__isnull=False,
        ).first()
        if not role:
            raise ValueError("The prescribing practitioner requires an active tenant organization and location role.")

        resource_id = domain_command.get("id")
        item = PrescriptionItem.all_objects.select_for_update().filter(id=resource_id, tenant_id=tenant_id).first() if resource_id else None
        if item:
            prescription = item.prescription
            if prescription.workflow_state != "DRAFT":
                raise ValueError("A MedicationRequest cannot modify a prescription after clinical review begins.")
            if str(prescription.patient_id) != str(patient_id) or str(prescription.practitioner_id) != str(practitioner_id):
                raise ValueError("MedicationRequest patient and requester are immutable.")
        else:
            identifier = str(domain_command.get("identifier") or f"FHIR-{uuid.uuid4()}")[:80]
            prescription = Prescription.all_objects.create(
                tenant_id=tenant_id,
                patient_id=patient_id,
                practitioner_id=practitioner_id,
                organization=role.organization,
                location=role.location,
                prescription_number=identifier,
                status="DRAFT",
                workflow_state="DRAFT",
            )
            item = PrescriptionItem(
                id=uuid.UUID(str(resource_id)) if resource_id else uuid.uuid4(),
                tenant_id=tenant_id,
                prescription=prescription,
            )
        line = (domain_command.get("items") or [{}])[0]
        item.canonical_medicine_id = line.get("medication_id")
        item.medication_name = line.get("medication_name") or "Medication"
        item.quantity = line.get("quantity") or 1
        item.refills_authorized = line.get("refills_authorized") or 0
        item.dosage_instruction = line.get("dosage_instruction") or "As directed"
        item.save()
        return item
