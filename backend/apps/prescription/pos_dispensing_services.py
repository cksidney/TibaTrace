from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryBatch
from apps.medicines.models import CommercialSKU
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingCheck,
    DispensingEpisode,
    DispensingLine,
    PatientCounselling,
    PosShiftRecord,
    Prescription,
)
from apps.prescription.services.clinical_dispensing import (
    MedicineSupplyService,
    _active_verification,
    _require_capability,
)
from apps.workflows.service import emit_event

# The POS surface is a thin, governed front-end over the authoritative clinical
# dispensing services. It must never post inventory, create supplies, or mutate
# episode state on its own -- every business action is delegated so that the
# clinical gates (pharmacist verification, context hash, final check,
# counselling, batch quality, controlled separation of duties, locking and
# idempotency) apply identically whether an action originates at the POS or
# anywhere else.

#: Payment gate states that permit medicine supply. Mirrors
#: MedicineSupplyService.ALLOWED_PAYMENT_STATES, which is the authority.
PAYMENT_STATES_ALLOWING_SUPPLY = MedicineSupplyService.ALLOWED_PAYMENT_STATES


class PosDispensingQueueService:
    @staticmethod
    def get_queue(*, tenant, branch=None, status=None):
        # Accepts a Tenant or a tenant id. Filtering on `tenant=None` silently
        # matches nothing, so a missing tenant is refused rather than answered
        # with an empty queue that reads as "no patients waiting".
        if tenant is None:
            raise ValueError("get_queue requires a tenant; refusing to return an unscoped queue.")
        qs = DispensingEpisode.all_objects.filter(tenant_id=getattr(tenant, "pk", tenant))
        if branch:
            qs = qs.filter(branch=branch)
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-initiated_at")

    @staticmethod
    @transaction.atomic
    def transition_state(*, episode, new_status, actor=None, notes=""):
        _require_capability(actor, episode.tenant_id, "dispensing.prepare")

        allowed_transitions = {
            "DRAFT": ["PREPARING", "ON_HOLD", "CANCELLED"],
            "PREPARING": ["CHECKING", "ON_HOLD", "CANCELLED"],
            "CHECKING": ["READY_FOR_PAYMENT", "READY_FOR_SUPPLY", "REJECTED", "ON_HOLD"],
            "READY_FOR_PAYMENT": ["PAID", "ON_HOLD", "CANCELLED"],
            "PAID": ["READY_FOR_COLLECTION", "READY_FOR_SUPPLY", "ON_HOLD"],
            "READY_FOR_SUPPLY": ["PARTIALLY_SUPPLIED", "SUPPLIED", "ON_HOLD"],
            "READY_FOR_COLLECTION": ["READY_FOR_SUPPLY", "ON_HOLD"],
            "PARTIALLY_SUPPLIED": ["SUPPLIED", "CLOSED", "ON_HOLD"],
            "SUPPLIED": ["CLOSED"],
            "ON_HOLD": ["PREPARING", "CHECKING", "READY_FOR_PAYMENT", "CANCELLED"],
            "REJECTED": [],
            "CANCELLED": [],
            "CLOSED": [],
        }

        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=episode.pk, tenant_id=episode.tenant_id
        )
        current = episode.status
        if new_status not in allowed_transitions.get(current, []):
            raise ValidationError(f"Invalid state transition from {current} to {new_status}")

        # Clinical gate: an episode may not become payable or suppliable until a
        # current pharmacist verification and an independent final check exist.
        if new_status in ["READY_FOR_PAYMENT", "READY_FOR_SUPPLY"]:
            # Raises if absent or if the prescription changed since verification.
            _active_verification(episode.prescription)
            final_check = DispensingCheck.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
                outcome="PASSED",
            ).exists()
            if not final_check:
                raise ValidationError(
                    "An independent final check must pass before payment or supply."
                )

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
    def verify_batch(*, tenant, sku_id, batch_number, expiry_date=None, quantity_scanned=Decimal("1"), location=None):
        def _reject(reason, **overrides):
            payload = {
                "valid": False,
                "reason": reason,
                "sku_match": False,
                "batch_found": False,
                "release_status": "UNKNOWN",
                "is_recalled": False,
                "is_expired": False,
                "quantity_available": Decimal("0"),
            }
            payload.update(overrides)
            return payload

        try:
            sku = CommercialSKU.all_objects.get(tenant=tenant, pk=sku_id)
        except CommercialSKU.DoesNotExist:
            return _reject("Commercial SKU not found")

        batch = InventoryBatch.all_objects.filter(
            tenant=tenant,
            sku=sku,
            manufacturer_batch_number=batch_number,
        ).first()

        if not batch:
            return _reject(
                f"Batch {batch_number} not found for SKU {sku.sku_code}",
                sku_match=True,
            )

        found = {"sku_match": True, "batch_found": True}
        is_expired = batch.expiry_date < date.today()
        is_recalled = (
            batch.recall_status != InventoryBatch.RecallStatus.NONE
            or batch.quality_status == "RECALLED"
        )

        # A scanned expiry that disagrees with the batch master means the
        # physical pack does not match the record -- never silently accept it.
        if expiry_date and batch.expiry_date != expiry_date:
            return _reject(
                f"Scanned expiry {expiry_date} does not match batch record {batch.expiry_date}",
                release_status=batch.quality_status,
                is_recalled=is_recalled,
                is_expired=is_expired,
                **found,
            )

        if is_expired:
            return _reject(
                f"Batch {batch_number} has expired on {batch.expiry_date}",
                release_status=batch.quality_status,
                is_recalled=is_recalled,
                is_expired=True,
                **found,
            )

        if is_recalled:
            return _reject(
                f"Batch {batch_number} is under RECALL quarantine",
                release_status="RECALLED",
                is_recalled=True,
                **found,
            )

        if batch.quality_status != InventoryBatch.QualityStatus.RELEASED:
            return _reject(
                f"Batch {batch_number} is not released for dispensing (status: {batch.quality_status})",
                release_status=batch.quality_status,
                **found,
            )

        # Read-only availability lookup. Deliberately does not use
        # InventoryBalanceService.get_balance, which locks and upserts rows and
        # so must not be called from this non-transactional probe.
        balances = InventoryBalance.all_objects.filter(
            tenant=tenant, sku=sku, inventory_batch=batch
        )
        if location is not None:
            balances = balances.filter(location=location)
        available = balances.aggregate(total=Sum("available"))["total"] or Decimal("0")
        requested = Decimal(str(quantity_scanned or 0))
        if requested > available:
            return _reject(
                f"Insufficient quantity in batch {batch_number}: {available} available, {requested} scanned",
                release_status="RELEASED",
                quantity_available=available,
                **found,
            )

        return {
            "valid": True,
            "reason": "Batch verified successfully",
            "release_status": "RELEASED",
            "is_recalled": False,
            "is_expired": False,
            "quantity_available": available,
            **found,
        }


class PosPaymentOrchestrationService:
    @staticmethod
    @transaction.atomic
    def process_payment(
        *,
        episode,
        tender_type,
        paid_amount,
        payment_reference="",
        cashier=None,
        idempotency_key=None,
    ):
        _require_capability(cashier, episode.tenant_id, "prescriptions.record_payment")

        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=episode.pk, tenant_id=episode.tenant_id
        )

        # Replay of the same payment attempt is a no-op, not a second payment.
        if episode.payment_idempotency_key == idempotency_key:
            return {
                "success": True,
                "episode_id": str(episode.id),
                "payment_state": episode.payment_state,
                "payment_reference": episode.payment_reference,
                "tender_type": episode.tender_type,
                "paid_amount": str(episode.paid_amount),
                "replayed": True,
            }

        if episode.payment_state == "PAID":
            raise ValidationError("Episode has already been paid.")

        if episode.status in ["CANCELLED", "REJECTED", "CLOSED"]:
            raise ValidationError(f"Cannot process payment for episode in state {episode.status}")

        # Payment is only reachable once the clinical gate has been passed, which
        # is what moves an episode into READY_FOR_PAYMENT.
        if episode.status != "READY_FOR_PAYMENT":
            raise ValidationError(
                f"Episode {episode.dispensing_number} is not ready for payment "
                f"(current status: {episode.status})"
            )

        amount = Decimal(str(paid_amount))
        if amount <= 0:
            raise ValidationError("Paid amount must be greater than zero.")

        expected = PosPaymentOrchestrationService.amount_due(episode=episode)
        if expected is not None and amount < expected:
            raise ValidationError(
                f"Paid amount {amount} is less than the amount due {expected}."
            )

        # Payment records commercial settlement only. It never touches inventory;
        # stock moves solely on confirmed physical supply.
        episode.payment_state = "PAID"
        episode.payment_reference = payment_reference or f"PAY-{idempotency_key[:24].upper()}"
        episode.tender_type = tender_type
        episode.paid_amount = amount
        episode.payment_idempotency_key = idempotency_key
        episode.status = "PAID"
        episode.save()

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="DISPENSING_PAYMENT_PROCESSED",
            payload={
                "tender_type": tender_type,
                "paid_amount": str(amount),
                "payment_reference": episode.payment_reference,
                "cashier_id": str(cashier.id) if cashier else None,
            },
        )

        return {
            "success": True,
            "episode_id": str(episode.id),
            "payment_state": "PAID",
            "payment_reference": episode.payment_reference,
            "tender_type": tender_type,
            "paid_amount": str(episode.paid_amount),
            "replayed": False,
        }

    @staticmethod
    def amount_due(*, episode):
        """Amount the episode expects to collect, or None when not priced.

        Returns None rather than zero when no priced sales order backs the
        episode, so that callers can distinguish "nothing to check against"
        from "nothing to pay".
        """
        order = episode.sales_order
        if order is None:
            return None
        return Decimal(str(order.total))


class PosPartialRepeatService:
    @staticmethod
    @transaction.atomic
    def dispense_partial(
        *,
        episode,
        dispensing_line_id,
        quantity_supplied,
        reason="",
        actor=None,
        idempotency_key=None,
    ):
        """Supply part of a line.

        Delegates to the authoritative supply service so that the partial supply
        posts inventory, consumes prescription authorization and repeats, and
        records supply lines exactly as a full supply does.
        """
        line = DispensingLine.all_objects.get(
            tenant=episode.tenant, pk=dispensing_line_id, episode=episode
        )
        qty = Decimal(str(quantity_supplied))
        if qty <= 0:
            raise ValidationError("Quantity supplied must be greater than zero")

        supply = MedicineSupplyService.supply(
            episode=episode,
            actor=actor,
            idempotency_key=idempotency_key,
            line_quantities={str(line.id): qty},
            partial_reason=reason,
        )

        line.refresh_from_db()
        outstanding = line.quantity_authorized - line.quantity_supplied
        return {
            "supply_id": str(supply.id),
            "line_id": str(line.id),
            "quantity_authorized": str(line.quantity_authorized),
            "quantity_supplied": str(line.quantity_supplied),
            "outstanding_balance": str(outstanding),
            "status": line.status,
        }

    @staticmethod
    def check_repeat_eligibility(*, tenant, prescription_id):
        """Read-only eligibility probe.

        This never consumes a repeat. Repeats are consumed transactionally by
        MedicineSupplyService.supply at the moment of confirmed supply, which is
        what prevents two terminals from claiming the same final repeat.
        """
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
            "advisory_only": True,
        }


class PosControlledMedicineService:
    @staticmethod
    @transaction.atomic
    def verify_controlled_authority(*, episode, practitioner_id, collector_id_number, witness=None, actor=None):
        _require_capability(actor, episode.tenant_id, "prescriptions.controlled_verify")

        if not collector_id_number:
            raise ValidationError("Collector identity number is mandatory for controlled medicines")

        try:
            practitioner = Practitioner.all_objects.get(
                tenant_id=episode.tenant_id, pk=practitioner_id
            )
        except Practitioner.DoesNotExist:
            raise ValidationError("Prescriber not found for this tenant.") from None

        if practitioner.pk != episode.prescription.practitioner_id:
            raise ValidationError(
                "Prescriber does not match the prescribing practitioner on the prescription."
            )
        if not practitioner.controlled_medicine_authority:
            raise ValidationError(
                "Prescriber is not authorised to prescribe controlled medicines."
            )

        if witness is not None and actor is not None and witness.pk == actor.pk:
            raise ValidationError("The controlled-medicine witness must differ from the verifier.")

        episode.controlled_authority_checked = True
        episode.collector_id_number = collector_id_number
        if witness:
            episode.controlled_witness = witness
        episode.save()

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="CONTROLLED_AUTHORITY_VERIFIED",
            payload={
                "practitioner_id": str(practitioner.id),
                "witness_id": str(witness.id) if witness else None,
                "actor_id": str(actor.id) if actor else None,
            },
        )

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
        _require_capability(pharmacist, episode.tenant_id, "dispensing.counsel")

        counselling, _ = PatientCounselling.all_objects.get_or_create(
            tenant=episode.tenant,
            episode=episode,
            defaults={
                "patient": episode.patient,
                "counselling_required": True,
            },
        )
        counselling.counselling_completed = True
        counselling.warnings_explained = notes
        counselling.counselled_by = pharmacist
        counselling.save()

        episode.counselling_status = "COMPLETED"
        episode.save()

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="PATIENT_COUNSELLED",
            payload={"pharmacist_id": str(pharmacist.id) if pharmacist else None},
        )

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
        idempotency_key=None,
    ):
        """Confirm physical handover and supply the medicine.

        Collector identity is recorded here; the supply itself -- and therefore
        every clinical gate and the inventory posting -- is delegated to
        MedicineSupplyService, which is idempotent on idempotency_key.
        """
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        if not collector_name:
            raise ValidationError("Collector name is required to confirm collection.")

        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=episode.pk, tenant_id=episode.tenant_id
        )

        supply = MedicineSupplyService.supply(
            episode=episode,
            actor=actor,
            idempotency_key=idempotency_key,
        )

        # supply() advances episode.status; re-read before touching the row so
        # this write cannot clobber it, and persist only the collector fields.
        episode.refresh_from_db()

        # Only stamp collection details on the first (non-replayed) confirmation.
        if not episode.collected_at:
            episode.collector_name = collector_name
            episode.collector_id_number = collector_id_number
            episode.collector_phone = collector_phone
            episode.collector_relationship = collector_relationship
            episode.collection_proof_type = collection_proof_type
            episode.collected_at = timezone.now()
            episode.save(
                update_fields=[
                    "collector_name",
                    "collector_id_number",
                    "collector_phone",
                    "collector_relationship",
                    "collection_proof_type",
                    "collected_at",
                ]
            )

            emit_event(
                tenant_id=str(episode.tenant_id),
                aggregate_type="DispensingEpisode",
                aggregate_id=str(episode.id),
                event_type="MEDICINE_COLLECTED",
                payload={
                    "collector_name": collector_name,
                    "collector_relationship": collector_relationship,
                    "collection_proof_type": collection_proof_type,
                    "signature_ref": signature_ref,
                    "supply_id": str(supply.id),
                    "collected_at": episode.collected_at.isoformat(),
                },
            )

        return supply


class PosShiftService:
    @staticmethod
    @transaction.atomic
    def start_shift(
        *,
        tenant,
        shift_number,
        cashier=None,
        pharmacist=None,
        location=None,
        controlled_start_count=0,
        actor=None,
    ):
        _require_capability(actor or cashier, tenant.id, "pos.shift.manage")
        return PosShiftRecord.all_objects.create(
            tenant=tenant,
            shift_number=shift_number,
            cashier=cashier,
            pharmacist=pharmacist,
            location=location,
            started_at=timezone.now(),
            status=PosShiftRecord.Status.OPEN,
            controlled_stock_start_count=controlled_start_count,
        )

    @staticmethod
    @transaction.atomic
    def end_shift(*, shift, controlled_end_count=0, declaration_notes="", actor=None):
        _require_capability(actor or shift.cashier, shift.tenant_id, "pos.shift.manage")

        shift = PosShiftRecord.all_objects.select_for_update().get(
            pk=shift.pk, tenant_id=shift.tenant_id
        )
        if shift.status != PosShiftRecord.Status.OPEN:
            raise ValidationError(f"Shift {shift.shift_number} is not open.")

        # Episodes that are paid but not yet supplied, or mid-supply, must be
        # visible before a shift can be declared closed.
        outstanding = DispensingEpisode.all_objects.filter(
            tenant_id=shift.tenant_id,
            status__in=["PAID", "READY_FOR_COLLECTION", "READY_FOR_SUPPLY", "PARTIALLY_SUPPLIED"],
        ).count()

        shift.ended_at = timezone.now()
        shift.status = PosShiftRecord.Status.CLOSED
        shift.controlled_stock_end_count = controlled_end_count
        shift.declaration_notes = declaration_notes
        shift.outstanding_episode_count = outstanding
        shift.discrepancy_declared = (
            shift.controlled_stock_start_count != controlled_end_count or outstanding > 0
        )
        shift.save()

        emit_event(
            tenant_id=str(shift.tenant_id),
            aggregate_type="PosShiftRecord",
            aggregate_id=str(shift.id),
            event_type="POS_SHIFT_CLOSED",
            payload={
                "shift_number": shift.shift_number,
                "discrepancy_declared": shift.discrepancy_declared,
                "outstanding_episode_count": outstanding,
                "controlled_variance": controlled_end_count - shift.controlled_stock_start_count,
            },
        )
        return shift
