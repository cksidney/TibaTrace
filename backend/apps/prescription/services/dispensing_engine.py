from __future__ import annotations

from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from apps.medicines.models import Medicine
from apps.prescription.models import (
    Prescription,
    PrescriptionDispense,
    PrescriptionFill,
    PrescriptionItem,
    PrescriptionSubstitution,
)
from apps.prescription.services.workflow import PrescriptionWorkflowService


class DispensingEngine:
    @staticmethod
    def validate_dispense(prescription: Prescription, items_to_dispense: list[dict]) -> None:
        if prescription.workflow_state != "PAID":
            raise ValueError("Prescription must complete clinical review and payment before dispensing.")
        if not prescription.clinical_review_id or (
            prescription.clinical_context_hash != PrescriptionWorkflowService.context_hash(prescription)
        ):
            raise ValueError("Clinical approval is missing or stale.")
        if prescription.expires_at and prescription.expires_at < timezone.now():
            raise ValueError("Prescription has expired.")
        if not items_to_dispense:
            raise ValueError("At least one prescription item is required.")

        for requested in items_to_dispense:
            item = PrescriptionItem.all_objects.filter(
                id=requested.get("prescription_item_id"),
                tenant_id=prescription.tenant_id,
                prescription=prescription,
            ).first()
            if not item:
                raise ValueError("Prescription item is unavailable in the active tenant.")
            quantity = Decimal(str(requested.get("quantity") or "0"))
            if quantity <= 0:
                raise ValueError("Dispense quantity must be positive.")
            already_filled = sum(
                (fill.quantity_dispensed for fill in PrescriptionFill.all_objects.filter(
                    tenant_id=prescription.tenant_id,
                    item=item,
                )),
                Decimal("0"),
            )
            if already_filled + quantity > item.total_authorized_quantity:
                raise ValueError(f"Cannot exceed prescribed quantity for {item.medication_name}.")

            substitute_id = requested.get("substituted_medicine_id")
            if substitute_id and str(substitute_id) != str(item.canonical_medicine_id or ""):
                if prescription.substitution_policy == "NO_SUBSTITUTION":
                    raise ValueError("Substitution is not permitted for this prescription.")
                substitute = Medicine.all_objects.filter(id=substitute_id).filter(
                    models.Q(tenant_id=prescription.tenant_id) | models.Q(tenant__isnull=True, is_global=True)
                ).first()
                if not substitute:
                    raise ValueError("Substitute medicine is unavailable.")
                if item.canonical_medicine and substitute.dosage_form != item.canonical_medicine.dosage_form:
                    raise ValueError("Substitute dosage form does not match the prescribed medicine.")

    @staticmethod
    @transaction.atomic
    def execute_dispense(
        prescription: Prescription,
        location,
        items_to_dispense: list[dict],
        user,
        *,
        idempotency_key: str,
    ) -> PrescriptionDispense:
        if str(location.tenant_id) != str(prescription.tenant_id):
            raise ValueError("Dispensing location is outside the prescription tenant.")
        existing = PrescriptionDispense.all_objects.filter(
            tenant_id=prescription.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing

        DispensingEngine.validate_dispense(prescription, items_to_dispense)
        dispense = PrescriptionDispense.all_objects.create(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            location=location,
            dispensed_by=user,
            idempotency_key=idempotency_key,
        )
        for requested in items_to_dispense:
            item = PrescriptionItem.all_objects.get(
                id=requested["prescription_item_id"],
                tenant_id=prescription.tenant_id,
                prescription=prescription,
            )
            fill = PrescriptionFill.all_objects.create(
                tenant_id=prescription.tenant_id,
                dispense=dispense,
                item=item,
                quantity_dispensed=Decimal(str(requested["quantity"])),
                substituted_medicine_id=requested.get("substituted_medicine_id"),
            )
            if requested.get("substituted_medicine_id") and str(requested["substituted_medicine_id"]) != str(item.canonical_medicine_id):
                if not user.has_capability("dispensing.substitute", tenant_id=prescription.tenant_id):
                    raise PermissionError("Medicine substitution requires explicit capability.")
                reason = str(requested.get("substitution_reason") or "").strip()
                if not reason:
                    raise ValueError("Medicine substitution requires a reason.")
                PrescriptionSubstitution.all_objects.create(
                    tenant_id=prescription.tenant_id,
                    fill=fill,
                    original_item=item,
                    substitute_medicine_id=requested["substituted_medicine_id"],
                    reason=reason,
                    approved_by=user,
                )

        PrescriptionWorkflowService.transition(
            prescription_id=prescription.id,
            tenant_id=prescription.tenant_id,
            actor=user,
            target_state="DISPENSED",
        )
        return dispense
