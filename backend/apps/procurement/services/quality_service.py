from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.inventory.models import InventoryBatch
from apps.procurement.models import QualityDecision, ReceivedBatch, ReceivingInspection


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
        notes = notes or reason
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
            if temperature_excursion:
                batch.temperature_excursion = True
                batch.quality_status = ReceivedBatch.QualityStatus.QUARANTINED
            elif decision == "PASSED":
                batch.quality_status = ReceivedBatch.QualityStatus.PASSED
            else:
                batch.quality_status = ReceivedBatch.QualityStatus.FAILED
            batch.save()

        return inspection

    @staticmethod
    @transaction.atomic
    def release_quarantined_batch(*, goods_receipt, batch, decision_by, decision_notes="") -> QualityDecision:
        if batch.quality_status not in [ReceivedBatch.QualityStatus.QUARANTINED, ReceivedBatch.QualityStatus.PENDING_TESTING]:
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
            batch_number=batch.manufacturer_batch_number,
        ).first()

        if inv_batch:
            inv_batch.quality_status = "RELEASED"
            inv_batch.save()

        return decision
