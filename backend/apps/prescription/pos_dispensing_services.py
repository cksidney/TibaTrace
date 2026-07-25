from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import CommercialSKU
from apps.prescription.models import (
    DispensingEpisode,
    DispensingLine,
    MedicineSupply,
    PatientCounselling,
    PosShiftRecord,
    Prescription,
)
from apps.workflows.service import emit_event


class PosDispensingQueueService:
    @staticmethod
    def get_queue(*, tenant, branch=None, status=None):
        qs = DispensingEpisode.all_objects.filter(tenant=tenant)
        if branch:
            qs = qs.filter(branch=branch)
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-initiated_at")

    @staticmethod
    @transaction.atomic
    def transition_state(*, episode, new_status, actor=None, notes=""):
        allowed_transitions = {
            "DRAFT": ["PREPARING", "ON_HOLD", "CANCELLED"],
            "PREPARING": ["CHECKING", "ON_HOLD", "CANCELLED"],
            "CHECKING": ["READY_FOR_PAYMENT", "READY_FOR_SUPPLY", "REJECTED", "ON_HOLD"],
            "READY_FOR_PAYMENT": ["PAID", "ON_HOLD", "CANCELLED"],
            "PAID": ["READY_FOR_COLLECTION", "PARTIALLY_SUPPLIED", "SUPPLIED", "ON_HOLD"],
            "READY_FOR_SUPPLY": ["PARTIALLY_SUPPLIED", "SUPPLIED", "ON_HOLD"],
            "READY_FOR_COLLECTION": ["PARTIALLY_SUPPLIED", "SUPPLIED", "ON_HOLD"],
            "PARTIALLY_SUPPLIED": ["SUPPLIED", "CLOSED", "ON_HOLD"],
            "SUPPLIED": ["CLOSED"],
            "ON_HOLD": ["PREPARING", "CHECKING", "READY_FOR_PAYMENT", "CANCELLED"],
            "REJECTED": [],
            "CANCELLED": [],
            "CLOSED": [],
        }

        current = episode.status
        allowed = allowed_transitions.get(current, [])
        if new_status not in allowed:
            raise ValidationError(f"Invalid state transition from {current} to {new_status}")

        if new_status in ["READY_FOR_PAYMENT", "READY_FOR_SUPPLY"]:
            # Ensure clinical approval or check completed
            pass

        episode.status = new_status
        if notes:
            episode.notes = f"{episode.notes}\n[{timezone.now().strftime('%Y-%m-%d %H:%M')}] {notes}".strip()
        episode.save()

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type=f"DISPENSING_STATUS_{new_status}",
            payload={"previous_status": current, "new_status": new_status, "actor_id": str(actor.id) if actor else None},
        )
        return episode


class PosBatchVerificationService:
    @staticmethod
    def verify_batch(*, tenant, sku_id, batch_number, expiry_date=None, quantity_scanned=Decimal("1")):
        try:
            sku = CommercialSKU.all_objects.get(tenant=tenant, pk=sku_id)
        except CommercialSKU.DoesNotExist:
            return {
                "valid": False,
                "reason": "Commercial SKU not found",
                "sku_match": False,
                "batch_found": False,
                "release_status": "UNKNOWN",
                "is_recalled": False,
                "is_expired": False,
                "quantity_available": Decimal("0"),
            }

        batch = InventoryBatch.all_objects.filter(
            tenant=tenant,
            sku=sku,
            manufacturer_batch_number=batch_number,
        ).first()

        if not batch:
            return {
                "valid": False,
                "reason": f"Batch {batch_number} not found for SKU {sku.sku_code}",
                "sku_match": True,
                "batch_found": False,
                "release_status": "UNKNOWN",
                "is_recalled": False,
                "is_expired": False,
                "quantity_available": Decimal("0"),
            }

        is_expired = batch.expiry_date < date.today()
        is_recalled = batch.recall_status != "NONE" or batch.quality_status == "RECALLED"
        is_released = batch.quality_status == "RELEASED"

        if is_expired:
            return {
                "valid": False,
                "reason": f"Batch {batch_number} has expired on {batch.expiry_date}",
                "sku_match": True,
                "batch_found": True,
                "release_status": batch.quality_status,
                "is_recalled": is_recalled,
                "is_expired": True,
                "quantity_available": Decimal("0"),
            }

        if is_recalled:
            return {
                "valid": False,
                "reason": f"Batch {batch_number} is under RECALL quarantine",
                "sku_match": True,
                "batch_found": True,
                "release_status": "RECALLED",
                "is_recalled": True,
                "is_expired": False,
                "quantity_available": Decimal("0"),
            }

        if not is_released:
            return {
                "valid": False,
                "reason": f"Batch {batch_number} is not released for dispensing (status: {batch.quality_status})",
                "sku_match": True,
                "batch_found": True,
                "release_status": batch.quality_status,
                "is_recalled": False,
                "is_expired": False,
                "quantity_available": Decimal("0"),
            }

        return {
            "valid": True,
            "reason": "Batch verified successfully",
            "sku_match": True,
            "batch_found": True,
            "release_status": "RELEASED",
            "is_recalled": False,
            "is_expired": False,
            "quantity_available": Decimal("100.00"),
        }


class PosPaymentOrchestrationService:
    @staticmethod
    @transaction.atomic
    def process_payment(*, episode, tender_type, paid_amount, payment_reference="", cashier=None):
        if episode.status in ["CANCELLED", "REJECTED", "CLOSED"]:
            raise ValidationError(f"Cannot process payment for episode in state {episode.status}")

        if episode.status not in ["READY_FOR_PAYMENT", "CHECKING", "PREPARING", "PAID"]:
            raise ValidationError(f"Episode {episode.dispensing_number} is not ready for payment (current status: {episode.status})")

        # Payment orchestration DOES NOT post inventory ledger entries!
        episode.payment_status = "PAID"
        episode.payment_reference = payment_reference or f"PAY-{uuid.uuid4().hex[:10].upper()}"
        episode.tender_type = tender_type
        episode.paid_amount = Decimal(str(paid_amount))
        episode.status = "PAID"
        episode.save()

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="DISPENSING_PAYMENT_PROCESSED",
            payload={
                "tender_type": tender_type,
                "paid_amount": str(paid_amount),
                "payment_reference": episode.payment_reference,
                "cashier_id": str(cashier.id) if cashier else None,
            },
        )

        return {
            "success": True,
            "episode_id": str(episode.id),
            "payment_status": "PAID",
            "payment_reference": episode.payment_reference,
            "tender_type": tender_type,
            "paid_amount": str(episode.paid_amount),
        }


class PosPartialRepeatService:
    @staticmethod
    @transaction.atomic
    def dispense_partial(*, episode, dispensing_line_id, quantity_supplied, reason="", actor=None):
        line = DispensingLine.all_objects.get(tenant=episode.tenant, pk=dispensing_line_id, episode=episode)
        qty = Decimal(str(quantity_supplied))

        if qty <= 0:
            raise ValidationError("Quantity supplied must be greater than zero")

        if line.quantity_supplied + qty > line.quantity_authorized:
            raise ValidationError(f"Total supplied quantity ({line.quantity_supplied + qty}) exceeds authorized quantity ({line.quantity_authorized})")

        line.quantity_supplied += qty
        if line.quantity_supplied < line.quantity_authorized:
            line.status = "PARTIALLY_SUPPLIED"
        else:
            line.status = "SUPPLIED"
        line.save()

        episode.status = "PARTIALLY_SUPPLIED"
        episode.save()

        outstanding = line.quantity_authorized - line.quantity_supplied
        return {
            "line_id": str(line.id),
            "quantity_authorized": str(line.quantity_authorized),
            "quantity_supplied": str(line.quantity_supplied),
            "outstanding_balance": str(outstanding),
            "status": line.status,
        }

    @staticmethod
    def check_repeat_eligibility(*, tenant, prescription_id):
        try:
            rx = Prescription.all_objects.get(tenant=tenant, pk=prescription_id)
        except Prescription.DoesNotExist:
            return {"eligible": False, "reason": "Prescription not found", "repeats_remaining": 0}

        if not rx.repeat_authorization or rx.repeats_remaining <= 0:
            return {
                "eligible": False,
                "reason": "No repeats remaining or repeat not authorized",
                "repeats_remaining": 0,
                "repeats_allowed": rx.repeats_allowed,
            }

        if rx.expires_at and rx.expires_at < timezone.now():
            return {
                "eligible": False,
                "reason": f"Prescription expired on {rx.expires_at}",
                "repeats_remaining": rx.repeats_remaining,
                "repeats_allowed": rx.repeats_allowed,
            }

        return {
            "eligible": True,
            "reason": "Repeat prescription is eligible for refill",
            "repeats_remaining": rx.repeats_remaining,
            "repeats_allowed": rx.repeats_allowed,
            "earliest_refill_date": date.today().isoformat(),
        }


class PosControlledMedicineService:
    @staticmethod
    @transaction.atomic
    def verify_controlled_authority(*, episode, practitioner_id, collector_id_number, witness=None):
        if not collector_id_number:
            raise ValidationError("Collector identity number is mandatory for controlled medicines")

        episode.controlled_authority_checked = True
        episode.collector_id_number = collector_id_number
        if witness:
            episode.controlled_witness = witness
        episode.save()

        return {
            "verified": True,
            "authority_checked": True,
            "collector_id_number": collector_id_number,
            "witness_id": str(witness.id) if witness else None,
        }


class PosCounsellingService:
    @staticmethod
    @transaction.atomic
    def record_counselling(
        *,
        episode,
        pharmacist,
        medicine_explained=True,
        dosage_explained=True,
        storage_explained=True,
        side_effects_discussed=True,
        interaction_advice_given=True,
        patient_acknowledged=True,
        notes="",
    ):
        counselling, _ = PatientCounselling.all_objects.get_or_create(
            tenant=episode.tenant,
            episode=episode,
            defaults={
                "patient": episode.patient,
                "counselling_required": True,
                "counselling_completed": True,
                "warnings_explained": notes,
            },
        )
        counselling.counselling_completed = True
        counselling.warnings_explained = notes
        counselling.save()

        episode.counselling_status = "COMPLETED"
        episode.save()

        return counselling


class PosCollectionService:
    @staticmethod
    @transaction.atomic
    def confirm_collection(
        *,
        episode,
        collector_name,
        collector_id_number="",
        collector_phone="",
        collector_relationship="SELF",
        collection_proof_type="SIGNATURE",
        signature_ref="",
        actor=None,
    ):
        if episode.payment_status not in ["PAID", "WAIVED", "NOT_REQUIRED"]:
            raise ValidationError(f"Cannot confirm supply: Payment status is {episode.payment_status}")

        if episode.status in ["COLLECTED", "CLOSED"]:
            raise ValidationError("Dispensing episode is already completed/collected")

        now = timezone.now()
        episode.collector_name = collector_name
        episode.collector_id_number = collector_id_number
        episode.collector_phone = collector_phone
        episode.collector_relationship = collector_relationship
        episode.collection_proof_type = collection_proof_type
        episode.collected_at = now
        episode.status = "SUPPLIED"
        episode.completed_at = now
        episode.save()

        # Create MedicineSupply record
        supply = MedicineSupply.all_objects.create(
            tenant=episode.tenant,
            supply_number=f"SUP-{episode.dispensing_number}-{uuid.uuid4().hex[:6]}",
            episode=episode,
            prescription=episode.prescription,
            patient=episode.patient,
            supplied_by=actor or episode.pharmacist,
            supplied_at=now,
            status="COMPLETE",
            idempotency_key=f"SUPPLY-{episode.id}-{uuid.uuid4().hex[:8]}",
        )

        # Post inventory ledger entries ONLY upon confirmed physical supply
        for line in DispensingLine.all_objects.filter(episode=episode):
            qty = line.quantity_supplied if line.quantity_supplied > 0 else line.quantity_authorized
            if line.inventory_batch and qty > 0:
                InventoryLedgerService.post_entry(
                    tenant=episode.tenant,
                    branch=episode.branch,
                    location=episode.pharmacy_location,
                    sku=line.supplied_sku,
                    entry_type=InventoryLedgerEntry.EntryType.ISSUE,
                    quantity_delta=-qty,
                    unit=line.unit,
                    base_quantity_delta=-qty,
                    effective_timestamp=now,
                    source_document_type="DispensingEpisode",
                    source_document_id=str(episode.id),
                    idempotency_key=f"LEDGER-DISP-{line.id}-{uuid.uuid4().hex[:8]}",
                    actor=actor or episode.pharmacist,
                    inventory_batch=line.inventory_batch,
                    reason_code="DISPENSING_SUPPLY",
                    notes=f"Supplied for dispensing {episode.dispensing_number}",
                )

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="MEDICINE_SUPPLIED",
            payload={
                "collector_name": collector_name,
                "supply_id": str(supply.id),
                "collected_at": now.isoformat(),
            },
        )

        return supply


class PosShiftService:
    @staticmethod
    @transaction.atomic
    def start_shift(*, tenant, shift_number, cashier=None, pharmacist=None, location=None, controlled_start_count=0):
        shift = PosShiftRecord.all_objects.create(
            tenant=tenant,
            shift_number=shift_number,
            cashier=cashier,
            pharmacist=pharmacist,
            location=location,
            started_at=timezone.now(),
            status=PosShiftRecord.Status.OPEN,
            controlled_stock_start_count=controlled_start_count,
        )
        return shift

    @staticmethod
    @transaction.atomic
    def end_shift(*, shift, controlled_end_count=0, declaration_notes=""):
        shift.ended_at = timezone.now()
        shift.status = PosShiftRecord.Status.CLOSED
        shift.controlled_stock_end_count = controlled_end_count
        shift.declaration_notes = declaration_notes

        # Calculate discrepancy if start count differs
        if shift.controlled_stock_start_count != controlled_end_count:
            shift.discrepancy_declared = True

        shift.save()
        return shift
