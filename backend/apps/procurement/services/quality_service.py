from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import InventoryBatch
from apps.procurement.models import GoodsReceipt, QualityDecision, ReceivedBatch, ReceivingInspection


class QualityService:
    """
    Authoritative domain service for quality inspection, cold-chain excursion logging,
    controlled medicine dual-witness verification, and quarantine & release decisions.
    """

    @staticmethod
    @transaction.atomic
    def record_inspection(*, goods_receipt, inspector, decision, temperature_excursion=False,
                          notes="", reason="") -> ReceivingInspection:
        """Record an inspection outcome.

        `reason` is the operational word for what `notes` holds -- an inspector
        typing why they quarantined a delivery. Accepted as either so the
        caller's vocabulary does not have to match the column's.
        """
        if inspector is None:
            raise ValidationError("A receiving inspection requires a named inspector.")
        notes = notes or reason
        if not str(notes or "").strip():
            raise ValidationError("A receiving inspection requires a reason.")
        if decision not in ReceivingInspection.Decision.values:
            raise ValidationError(f"{decision} is not a valid receiving-inspection decision.")
        inspection = ReceivingInspection.all_objects.create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            inspector=inspector,
            decision=decision,
            reason=notes,
        )

        # Batches hang off receipt lines, not off the receipt.
        for batch in ReceivedBatch.all_objects.filter(
            grn_line__goods_receipt=goods_receipt
        ):
            if temperature_excursion or decision in {
                ReceivingInspection.Decision.QUARANTINE,
                ReceivingInspection.Decision.HOLD_FOR_INVESTIGATION,
            }:
                batch.temperature_excursion = bool(temperature_excursion)
                batch.quality_status = ReceivedBatch.QualityStatus.QUARANTINED
            elif decision == ReceivingInspection.Decision.REJECT:
                batch.quality_status = ReceivedBatch.QualityStatus.REJECTED
                batch.rejected_quantity = batch.received_quantity
                batch.quarantined_quantity = 0
            elif decision == ReceivingInspection.Decision.DESTROY:
                batch.quality_status = ReceivedBatch.QualityStatus.DESTROYED
                batch.rejected_quantity = batch.received_quantity
                batch.quarantined_quantity = 0
            batch.save(
                update_fields=[
                    "temperature_excursion",
                    "quality_status",
                    "rejected_quantity",
                    "quarantined_quantity",
                    "updated_at",
                ]
            )

        if decision in {
            ReceivingInspection.Decision.QUARANTINE,
            ReceivingInspection.Decision.HOLD_FOR_INVESTIGATION,
            ReceivingInspection.Decision.RELEASE,
        }:
            goods_receipt.status = GoodsReceipt.Status.UNDER_INSPECTION
        elif decision == ReceivingInspection.Decision.REJECT:
            goods_receipt.status = GoodsReceipt.Status.REJECTED
        goods_receipt.save(update_fields=["status", "updated_at"])

        return inspection

    @staticmethod
    @transaction.atomic
    def release_quarantined_batch(*, goods_receipt, batch, decision_by, decision_notes="") -> QualityDecision:
        if batch.quality_status not in [
            ReceivedBatch.QualityStatus.QUARANTINED,
            ReceivedBatch.QualityStatus.PENDING_INSPECTION,
        ]:
            raise ValidationError(f"Batch {batch.manufacturer_batch_number} is not in quarantine status.")

        decision = QualityDecision.all_objects.create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            batch=batch,
            decision="RELEASED",
            decision_by=decision_by,
            decision_notes=decision_notes,
        )

        batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
        batch.save()

        inv_batch = InventoryBatch.all_objects.filter(
            tenant=goods_receipt.tenant,
            sku=batch.sku,
            manufacturer_batch_number=batch.manufacturer_batch_number,
        ).first()

        if inv_batch:
            inv_batch.quality_status = "RELEASED"
            inv_batch.save()

        return decision
