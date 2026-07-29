from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryBatch
from apps.medicines.models import CommercialSKU
from apps.pos_shift.authority import RegisterAuthorityService
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingCheck,
    DispensingEpisode,
    DispensingLine,
    MedicineSupply,
    PatientCounselling,
    PosShiftRecord,
    Prescription,
)
from apps.prescription.payment_models import PaymentSettlement
from apps.prescription.payment_services import (
    PaymentIntentService,
    PaymentSettlementService,
    PaymentTenderService,
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
            from apps.cds.pos_screening_services import PosClinicalApprovalService

            screening = PosClinicalApprovalService.assert_dispensing_episode_safe(episode=episode)
            from apps.cds.pos_screening_services import PosClinicalOverrideService

            PosClinicalOverrideService.consume_for_event(
                screening=screening,
                actor=actor,
                event=f"TRANSITION_{new_status}",
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
    """Compatibility adapter for the native dispensing payment command.

    The native clients still post one cash/card command to this endpoint.  It
    must therefore translate that command into payment-intent, tender and
    immutable-settlement facts; it must never mutate the episode's payment
    state as proof that money arrived.  Provider tenders deliberately stay out
    of this shortcut because their request acknowledgement is not settlement.
    """

    _INTENT_KEY_PREFIX = "pos-dispensing:intent:"
    _TENDER_KEY_PREFIX = "pos-dispensing:tender:"
    _SETTLEMENT_KEY_PREFIX = "pos-dispensing:settlement:"

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
        device_id="",
    ):
        _require_capability(cashier, episode.tenant_id, "prescriptions.record_payment")

        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=episode.pk, tenant_id=episode.tenant_id
        )

        settlement_key = PosPaymentOrchestrationService._key(
            PosPaymentOrchestrationService._SETTLEMENT_KEY_PREFIX, idempotency_key
        )
        existing_settlement = PaymentSettlement.all_objects.filter(
            tenant_id=episode.tenant_id, idempotency_key=settlement_key
        ).first()
        # A replay returns the original settlement fact even if the register or
        # shift has since closed. Re-validating current authority here would
        # turn a safe retry into an ambiguous outcome after a network failure.
        if existing_settlement:
            receipt = PosPaymentOrchestrationService._issue_receipt_safely(
                episode=episode,
                settlement=existing_settlement,
                actor=cashier,
            )
            return PosPaymentOrchestrationService._response(
                episode=episode,
                settlement=existing_settlement,
                replayed=True,
                receipt=receipt,
            )

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

        from apps.cds.pos_screening_services import PosClinicalApprovalService

        PosClinicalApprovalService.assert_dispensing_episode_safe(episode=episode)

        if tender_type == "MPESA":
            raise ValidationError(
                "M-PESA must be initiated and confirmed through the payment-intent workflow; "
                "a reference cannot mark an episode paid."
            )
        if tender_type not in {"CASH", "CARD"}:
            raise ValidationError(f"Unsupported direct-settlement tender type: {tender_type}")

        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=episode.tenant,
            branch=episode.branch,
            actor=cashier,
            device_id=device_id,
        )

        expected = PosPaymentOrchestrationService.amount_due(episode=episode)
        if expected is None:
            raise ValidationError(
                "Payment cannot start until an authoritative priced sales order is linked to the episode."
            )
        if expected <= 0:
            raise ValidationError(
                "Zero patient-payable episodes must complete through the governed zero-balance workflow."
            )

        amount = Decimal(str(paid_amount))
        if amount <= 0:
            raise ValidationError("Paid amount must be greater than zero.")
        if amount < expected:
            raise ValidationError(
                f"Paid amount {amount} is less than the amount due {expected}."
            )
        if tender_type == "CARD" and amount != expected:
            raise ValidationError(
                "A card confirmation must equal the server-derived amount due; "
                "cash change is not available for card tenders."
            )
        if tender_type == "CARD" and not str(payment_reference).strip():
            raise ValidationError("A card approval reference is required.")

        intent = PaymentIntentService.create(
            episode=episode,
            amount_due=expected,
            actor=cashier,
            idempotency_key=PosPaymentOrchestrationService._key(
                PosPaymentOrchestrationService._INTENT_KEY_PREFIX, idempotency_key
            ),
            device_id=device_id,
            register_id=authority.register.code,
        )
        tender = PaymentTenderService.allocate(
            intent=intent,
            tender_type=tender_type,
            allocated_amount=expected,
            actor=cashier,
            idempotency_key=PosPaymentOrchestrationService._key(
                PosPaymentOrchestrationService._TENDER_KEY_PREFIX, idempotency_key
            ),
            provider="MANUAL",
            register_id=authority.register.code,
            register_session=authority.session,
            operator_shift=authority.operator_shift,
        )
        if tender_type == "CASH":
            settlement = PaymentSettlementService.settle_cash(
                tender=tender,
                cash_received=amount,
                actor=cashier,
                idempotency_key=settlement_key,
                register_id=authority.register.code,
            )
        else:
            settlement = PaymentSettlementService.confirm_card(
                tender=tender,
                approval_reference=str(payment_reference).strip(),
                approved_amount=expected,
                actor=cashier,
                idempotency_key=settlement_key,
            )

        episode.refresh_from_db()
        if episode.payment_state != "PAID":
            raise ValidationError("Payment settlement did not clear the outstanding balance.")

        # These historical fields remain as a read-only compatibility mirror
        # for existing clients. The ledger settlement above is the financial
        # authority, and payment_state is projected there rather than written
        # by this adapter.
        reference = (
            str(payment_reference).strip()
            or settlement.provider_reference
            or f"CASH-{settlement.id.hex[:12].upper()}"
        )
        episode.payment_reference = reference
        episode.tender_type = tender_type
        episode.paid_amount = settlement.amount
        episode.payment_idempotency_key = idempotency_key
        episode.payment_register_session = authority.session
        episode.payment_operator_shift = authority.operator_shift
        episode.payment_device_id = device_id
        episode.status = "PAID"
        episode.save(
            update_fields=[
                "payment_reference",
                "tender_type",
                "paid_amount",
                "payment_idempotency_key",
                "payment_register_session",
                "payment_operator_shift",
                "payment_device_id",
                "status",
                "updated_at",
            ]
        )

        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="DispensingEpisode",
            aggregate_id=str(episode.id),
            event_type="DISPENSING_PAYMENT_SETTLED",
            payload={
                "tender_type": tender_type,
                "settled_amount": str(settlement.amount),
                "payment_reference": episode.payment_reference,
                "payment_intent_id": str(intent.id),
                "payment_tender_id": str(tender.id),
                "payment_settlement_id": str(settlement.id),
                "cashier_id": str(cashier.id) if cashier else None,
                "register_session_id": str(authority.session.id),
                "operator_shift_id": str(authority.operator_shift.id),
                "device_id": device_id,
            },
        )

        receipt = PosPaymentOrchestrationService._issue_receipt_safely(
            episode=episode,
            settlement=settlement,
            actor=cashier,
        )

        return PosPaymentOrchestrationService._response(
            episode=episode,
            settlement=settlement,
            replayed=False,
            receipt=receipt,
        )

    @staticmethod
    def _key(prefix, idempotency_key):
        return f"{prefix}{idempotency_key}"

    @staticmethod
    def _issue_receipt_safely(*, episode, settlement, actor):
        """Queue a receipt without allowing print infrastructure to undo payment.

        The ledger settlement has already been recorded. A failed queue write is
        visible to the operator and recoverable through the Print Centre, but
        it must never make a settled transaction look unpaid or replay its
        tender collection.
        """
        from apps.prescription.pos_printing_services import PosPrintDocumentService

        try:
            with transaction.atomic():
                document, job, _ = PosPrintDocumentService.issue_receipt_for_settlement(
                    episode=episode,
                    settlement=settlement,
                    actor=actor,
                )
            return {
                "document_number": document.document_number,
                "document_id": str(document.id),
                "print_job_id": str(job.id) if job else "",
                "status": job.status if job else "QUEUED",
            }
        except Exception:
            return {"status": "QUEUE_UNAVAILABLE"}

    @staticmethod
    def _response(*, episode, settlement, replayed, receipt=None):
        tender = settlement.payment_tender
        return {
            "success": True,
            "episode_id": str(episode.id),
            "payment_state": episode.payment_state,
            "payment_reference": episode.payment_reference
            or settlement.provider_reference
            or f"CASH-{settlement.id.hex[:12].upper()}",
            "tender_type": tender.tender_type,
            "paid_amount": str(settlement.amount),
            "replayed": replayed,
            "receipt": receipt or {"status": "QUEUE_UNAVAILABLE"},
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


class PosActionReconciliationService:
    """Answer a recovery query using immutable server facts, never screen state."""

    @staticmethod
    def reconcile(*, episode, action_type, idempotency_key, actor):
        _require_capability(actor, episode.tenant_id, "dispensing.read")
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        if action_type == "PAYMENT":
            settlement = PaymentSettlement.all_objects.filter(
                tenant_id=episode.tenant_id,
                payment_tender__payment_intent__dispensing_episode=episode,
                idempotency_key=PosPaymentOrchestrationService._key(
                    PosPaymentOrchestrationService._SETTLEMENT_KEY_PREFIX,
                    key,
                ),
            ).first()
            return {
                "action_type": action_type,
                "idempotency_key": key,
                "applied": bool(settlement),
                "authoritative_reference": str(settlement.id) if settlement else "",
            }

        if action_type in {"COLLECTION", "SUPPLY"}:
            supply = MedicineSupply.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
                idempotency_key=key,
            ).first()
            return {
                "action_type": action_type,
                "idempotency_key": key,
                "applied": bool(supply),
                "authoritative_reference": str(supply.id) if supply else "",
            }

        raise ValidationError({"action_type": "This action type cannot be reconciled."})


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
