from typing import Optional

from django.db import models

from apps.fhir.services.search_utils import bounded_count, reference_id
from apps.prescription.models import PrescriptionFill, PrescriptionItem
from apps.prescription.services.dispensing_engine import DispensingEngine


class MedicationDispenseLookupService:
    @staticmethod
    def get_by_id(resource_id: str, tenant_id: str) -> Optional[PrescriptionFill]:
        return PrescriptionFill.all_objects.filter(
            id=resource_id,
            tenant_id=tenant_id,
            dispense__tenant_id=tenant_id,
            item__tenant_id=tenant_id,
        ).first()

    @staticmethod
    def search(params, tenant_id):
        queryset = PrescriptionFill.all_objects.filter(tenant_id=tenant_id).select_related(
            "dispense", "item__prescription"
        )
        if params.get("_id"):
            queryset = queryset.filter(id=params["_id"])
        if params.get("identifier"):
            queryset = queryset.filter(dispense__idempotency_key=str(params["identifier"]).split("|")[-1])
        if params.get("subject"):
            queryset = queryset.filter(item__prescription__patient_id=reference_id(params["subject"], "Patient"))
        if params.get("prescription"):
            queryset = queryset.filter(item_id=reference_id(params["prescription"], "MedicationRequest"))
        if params.get("status"):
            queryset = queryset.filter(dispense__status=str(params["status"]).upper())
        if params.get("medication"):
            medication_id = reference_id(params["medication"], "Medication")
            queryset = queryset.filter(models.Q(substituted_medicine_id=medication_id) | models.Q(item__canonical_medicine_id=medication_id))
        return list(queryset.order_by("-dispense__dispensed_at")[: bounded_count(params)])

    @staticmethod
    def process_domain_command(domain_command: dict, context: dict) -> PrescriptionFill:
        tenant_id = context.get("tenant_id")
        user = context.get("user")
        if not tenant_id or not user:
            raise ValueError("Authenticated tenant context is required for dispensing.")
        item = PrescriptionItem.all_objects.select_related("prescription__location").filter(
            id=domain_command.get("prescription_item_id"), tenant_id=tenant_id
        ).first()
        if not item:
            raise ValueError("Authorizing MedicationRequest is unavailable in the active tenant.")
        key = str(domain_command.get("identifier") or "").strip()
        if not key:
            raise ValueError("A MedicationDispense identifier is required for idempotency.")
        dispense = DispensingEngine.execute_dispense(
            prescription=item.prescription,
            location=item.prescription.location,
            items_to_dispense=[
                {
                    "prescription_item_id": str(item.id),
                    "quantity": domain_command.get("quantity_dispensed") or 1,
                    "substituted_medicine_id": domain_command.get("medication_id"),
                }
            ],
            user=user,
            idempotency_key=key,
        )
        return PrescriptionFill.all_objects.get(tenant_id=tenant_id, dispense=dispense, item=item)
