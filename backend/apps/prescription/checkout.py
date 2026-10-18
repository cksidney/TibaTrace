"""Till checkout commands: the same ledger for dispensing and retail.

A browser supplies amounts and a stable command key, never payment state.
Provider acknowledgements remain pending until a server-side query confirms.
"""


from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.money import format_money
from apps.pos_shift.authority import RegisterAuthorityService
from apps.prescription.payment_api.serializers import PaymentIntentSerializer
from apps.prescription.payment_models import PaymentIntent, PaymentTender
from apps.prescription.payment_services import (
    PaymentIntentService,
    PaymentSettlementService,
    PaymentTenderService,
    lock_intent,
)
from apps.prescription.services.clinical_dispensing import _require_capability


class CheckoutService:
    @staticmethod
    def relation(source):
        return (
            {"retail_transaction": source}
            if source._meta.model_name == "postransaction"
            else {"dispensing_episode": source}
        )

    @classmethod
    def intent(cls, source):
        return (
            PaymentIntent.all_objects.filter(tenant_id=source.tenant_id, **cls.relation(source))
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def snapshot(cls, *, source, actor):
        from apps.prescription.payment_connections import payment_options

        intent = cls.intent(source)
        due = intent.amount_due if intent else cls.amount_due(source)
        from apps.prescription.fiscal import FiscalService

        serialised_intent = PaymentIntentSerializer(intent).data if intent else None
        from apps.prescription.payment_models import PaymentReversal
        voids = PaymentReversal.all_objects.filter(settlement__payment_tender__payment_intent=intent, status="REQUESTED").select_related("settlement__payment_tender") if intent else []
        if not intent and source._meta.model_name == "postransaction" and source.state == "COMPLETED":
            from apps.pos_transactions.models import RetailCashReceipt
            receipt = RetailCashReceipt.all_objects.filter(tenant=source.tenant, transaction=source).first()
            if receipt:
                serialised_intent = {"id": str(receipt.pk), "amount_remaining": "0.00", "effective_settled": format_money(receipt.amount), "status": "SETTLED", "tenders": []}
        return {
            "sale_state": getattr(source, "state", getattr(source, "status", "")),
            "fiscal": FiscalService.status(source),
            "source_id": str(source.pk),
            "amount_due": format_money(due) if due is not None else None,
            "currency": intent.currency if intent else getattr(source, "currency", "KES"),
            "intent": serialised_intent,
            "methods": payment_options(tenant=source.tenant, branch=source.branch),
            "can_reverse": actor.has_capability("pos.payment.reverse", tenant_id=source.tenant_id),
            "can_request_void": actor.has_capability("pos.refund.request", tenant_id=source.tenant_id),
            "can_approve_void": actor.has_capability("pos.refund.approve", tenant_id=source.tenant_id),
            "voids": [{"id": str(item.pk), "method": item.settlement.payment_tender.tender_type, "amount": format_money(item.amount), "reason": item.reason, "own_request": item.requested_by_id == actor.pk} for item in voids],
        }

    @staticmethod
    def amount_due(source):
        if source._meta.model_name == "postransaction":
            return source.total
        from apps.prescription.pos_dispensing_services import PosPaymentOrchestrationService

        return PosPaymentOrchestrationService.amount_due(episode=source)

    @classmethod
    def authority(cls, *, source, actor, device_id):
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=source.tenant, branch=source.branch, actor=actor, device_id=device_id
        )
        if source._meta.model_name == "postransaction":
            from apps.pos_transactions.services import PosRetailService

            PosRetailService._validate_transaction_context(source, authority, actor=actor, device_id=device_id)
            if source.state not in {"READY_FOR_PAYMENT", "PAYMENT_IN_PROGRESS"}:
                raise ValidationError("Prepare this basket for payment before collecting money.")
        else:
            _require_capability(actor, source.tenant_id, "prescriptions.record_payment")
            if source.status != "READY_FOR_PAYMENT":
                raise ValidationError("The prescription is not ready for payment.")
            from apps.cds.pos_screening_services import PosClinicalApprovalService

            PosClinicalApprovalService.assert_dispensing_episode_safe(episode=source)
        return authority

    @classmethod
    def open(cls, *, source, actor, device_id, authority):
        intent = cls.intent(source)
        if intent:
            if intent.device_id != device_id or intent.register_id != authority.register.code:
                raise ValidationError("This payment belongs to a different device or register.")
            if intent.status not in {"OPEN", "CREATED", "PARTIALLY_SETTLED"}:
                raise ValidationError("This payment is not open for further collection.")
            return intent
        amount = cls.amount_due(source)
        if amount is None or amount <= 0:
            raise ValidationError(
                "An authoritative positive price is required; zero balance requires exemption approval."
            )
        if source._meta.model_name != "postransaction":
            return PaymentIntentService.create(
                episode=source,
                amount_due=amount,
                actor=actor,
                idempotency_key=f"checkout:{source.pk}",
                device_id=device_id,
                register_id=authority.register.code,
            )
        from apps.inventory.models import InventoryBalance
        from apps.inventory.services import InventoryReservationService

        # Stable balance locks protect reservation selection across two tills.
        from apps.pos_transactions.models import PosTransactionLine
        lines = list(PosTransactionLine.all_objects.filter(tenant=source.tenant, transaction=source).select_related("sku__package_definition").order_by("sku_id"))
        for line in lines:
            if not line.sku.stock_tracking_required:
                continue
            list(
                InventoryBalance.all_objects.select_for_update()
                .filter(tenant=source.tenant, location=source.store, sku=line.sku)
                .order_by("pk")
            )
            reservation = InventoryReservationService.reserve_stock(
                tenant=source.tenant,
                branch=source.branch,
                source_location=source.store,
                sku=line.sku,
                requested_quantity=line.quantity,
                purpose="POS_CHECKOUT",
                actor=actor,
                idempotency_key=f"checkout:{source.pk}:{line.pk}",
                minimum_expiry_date=timezone.localdate() + timedelta(days=1),
            )
            reservation.source_document = str(source.pk)
            reservation.save(update_fields=["source_document"])
        intent = PaymentIntent.all_objects.create(
            tenant=source.tenant,
            branch=source.branch,
            retail_transaction=source,
            amount_due=amount,
            currency=source.currency,
            status="OPEN",
            device_id=device_id,
            register_id=authority.register.code,
            created_by=actor,
            idempotency_key=f"checkout:{source.pk}",
        )
        source.state = "PAYMENT_IN_PROGRESS"
        source.save(update_fields=["state", "updated_at"])
        return intent

    @classmethod
    @transaction.atomic
    def collect(cls, *, source, actor, device_id, tender_type, amount, cash_received, reference, idempotency_key):
        source = type(source).all_objects.select_for_update().get(pk=source.pk, tenant_id=source.tenant_id)
        # Read a previous result before checking the current shift or state.
        replay = PaymentTender.all_objects.filter(tenant_id=source.tenant_id, idempotency_key=idempotency_key).first()
        if replay:
            if (
                not PaymentIntent.all_objects.filter(tenant_id=source.tenant_id, pk=replay.payment_intent_id, **cls.relation(source)).exists()
                or replay.tender_type != tender_type
                or replay.allocated_amount != amount
                or replay.payment_intent.device_id != device_id
                or replay.created_by_id != actor.pk
                or (tender_type == "CASH" and replay.cash_received != cash_received)
                or (tender_type == "CARD" and replay.external_reference != reference)
            ):
                raise ValidationError("This retry key belongs to a different payment command.")
            return cls.snapshot(source=source, actor=actor)
        if tender_type not in {"CASH", "CARD"}:
            raise ValidationError("Provider payments must use initiation and status verification.")
        if tender_type == "CARD":
            from apps.prescription.payment_connections import card_manual_fallback_allowed, connection

            card_config = connection(tenant=source.tenant, branch=source.branch, provider="CARD")
            if card_config.get("enabled") and not card_manual_fallback_allowed(
                tenant=source.tenant, branch=source.branch
            ):
                raise ValidationError(
                    "This branch uses an integrated card terminal. Start the card provider request; "
                    "manual terminal confirmation is disabled."
                )
        capability = "pos.payment.cash.accept" if tender_type == "CASH" else "pos.payment.card.confirm"
        _require_capability(actor, source.tenant_id, capability)
        authority = cls.authority(source=source, actor=actor, device_id=device_id)
        intent = cls.open(source=source, actor=actor, device_id=device_id, authority=authority)
        if amount <= 0 or amount > intent.amount_remaining:
            raise ValidationError("Payment allocation must be positive and cannot exceed the remaining balance.")
        tender = PaymentTenderService.allocate(
            intent=intent,
            tender_type=tender_type,
            allocated_amount=amount,
            actor=actor,
            idempotency_key=idempotency_key,
            register_id=authority.register.code,
            register_session=authority.session,
            operator_shift=authority.operator_shift,
        )
        if tender_type == "CASH":
            settlement = PaymentSettlementService.settle_cash(
                tender=tender,
                cash_received=cash_received,
                actor=actor,
                idempotency_key=f"checkout-settle:{idempotency_key}",
                register_id=authority.register.code,
            )
        else:
            if not reference.strip():
                raise ValidationError("Enter the approval reference from the card terminal.")
            settlement = PaymentSettlementService.confirm_card(
                tender=tender,
                approval_reference=reference,
                approved_amount=amount,
                actor=actor,
                idempotency_key=f"checkout-settle:{idempotency_key}",
            )
        completion_error = ""
        try:
            with transaction.atomic():
                cls.complete(source=source, actor=actor, intent=intent, settlement=settlement, device_id=device_id)
        except ValidationError:
            completion_error = "Payment is recorded. Stock or register context needs review before sale completion. Do not collect again."
        source.refresh_from_db()
        result = cls.snapshot(source=source, actor=actor)
        result["completion_error"] = completion_error
        return result

    @classmethod
    def complete(cls, *, source, actor, intent, settlement, device_id):
        intent.refresh_from_db()
        if source._meta.model_name == "postransaction":
            if intent.status == "SETTLED":
                from apps.pos_transactions.services import PosRetailService

                PosRetailService.settle_cash(
                    tenant=source.tenant,
                    transaction_id=source.pk,
                    actor=actor,
                    device_id=device_id,
                    cash_received=source.total,
                    idempotency_key=f"checkout-receipt:{intent.pk}",
                    _settled_intent=intent,
                )
                source.refresh_from_db()
        else:
            source.refresh_from_db()
            if intent.status == "SETTLED" and source.status == "READY_FOR_PAYMENT":
                source.status = "PAID"
            source.payment_register_session = settlement.payment_tender.register_session
            source.payment_operator_shift = settlement.payment_tender.operator_shift
            source.payment_device_id = device_id
            source.save(
                update_fields=["status", "payment_register_session", "payment_operator_shift", "payment_device_id"]
            )
            from apps.prescription.pos_dispensing_services import PosPaymentOrchestrationService

            PosPaymentOrchestrationService._issue_receipt_safely(episode=source, settlement=settlement, actor=actor)
        from apps.prescription.fiscal import FiscalService

        FiscalService.enqueue(source=source)

    @classmethod
    @transaction.atomic
    def finish_paid(cls, *, source, actor, device_id):
        _require_capability(actor, source.tenant_id, "pos.transaction.create" if source._meta.model_name == "postransaction" else "prescriptions.record_payment")
        from apps.prescription.payment_models import PaymentSettlement
        source = type(source).all_objects.select_for_update().get(pk=source.pk, tenant_id=source.tenant_id)
        intent = cls.intent(source)
        if not intent or intent.status != "SETTLED" or intent.device_id != device_id:
            raise ValidationError("Only this device's fully settled sale can be completed.")
        if source._meta.model_name == "postransaction" and source.state == "COMPLETED":
            return cls.snapshot(source=source, actor=actor)
        settlement = PaymentSettlement.all_objects.filter(payment_tender__payment_intent=intent).order_by("-settled_at").first()
        if not settlement:
            raise ValidationError("No settlement evidence exists.")
        cls.complete(source=source, actor=actor, intent=intent, settlement=settlement, device_id=device_id)
        source.refresh_from_db()
        return cls.snapshot(source=source, actor=actor)

    @classmethod
    def initiate(cls, *, source, actor, device_id, tender_type="MPESA", amount, phone_number="", idempotency_key):
        from apps.prescription.payment_connections import card_terminal_adapter, mpesa_adapter
        from apps.prescription.payment_models import PaymentAttempt
        from apps.prescription.payment_services import payload_hash

        if tender_type not in {"MPESA", "CARD"}:
            raise ValidationError("Only configured card and M-PESA providers can be initiated.")
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0:
            raise ValidationError("Provider allocation must be positive.")
        if tender_type == "MPESA":
            from apps.prescription.payment_providers_mpesa import normalise_msisdn

            phone_number = normalise_msisdn(phone_number)
        command_hash = payload_hash({
            "tender_type": tender_type, "amount": str(amount.quantize(Decimal("0.01"))),
            "device_id": device_id, "phone_number": phone_number if tender_type == "MPESA" else "",
        })
        with transaction.atomic():
            source = type(source).all_objects.select_for_update().get(pk=source.pk, tenant_id=source.tenant_id)
            previous = PaymentTender.all_objects.filter(
                tenant_id=source.tenant_id, idempotency_key=idempotency_key
            ).first()
            if previous:
                original_attempt = PaymentAttempt.all_objects.filter(
                    payment_tender=previous, idempotency_key=f"checkout-attempt:{idempotency_key}"
                ).first()
                if (
                    not PaymentIntent.all_objects.filter(
                        tenant_id=source.tenant_id, pk=previous.payment_intent_id, **cls.relation(source)
                    ).exists()
                    or previous.allocated_amount != amount
                    or previous.created_by_id != actor.pk
                    or previous.tender_type != tender_type
                    or previous.payment_intent.device_id != device_id
                    or not original_attempt
                    or (original_attempt.request_payload_hash and original_attempt.request_payload_hash != command_hash)
                ):
                    raise ValidationError("This provider retry key belongs to another command.")
                return cls.snapshot(source=source, actor=actor)
            if tender_type == "MPESA":
                provider_code = "MPESA"
                adapter = mpesa_adapter(tenant=source.tenant, branch=source.branch)
            else:
                provider_code, adapter, adapter_config = card_terminal_adapter(
                    tenant=source.tenant, branch=source.branch
                )
            authority = cls.authority(source=source, actor=actor, device_id=device_id)
            _require_capability(actor, source.tenant_id, "pos.payment.provider.initiate")
            intent = cls.open(source=source, actor=actor, device_id=device_id, authority=authority)
            if amount <= 0 or amount > intent.amount_remaining:
                raise ValidationError("Provider allocation must be positive and within the remaining balance.")
            context = {
                "currency": intent.currency,
                "device_id": device_id,
                "register_id": authority.register.code,
            }
            if tender_type == "MPESA":
                if amount != amount.to_integral_value():
                    raise ValidationError("M-PESA allocation must be whole shillings.")
                context["phone_number"] = phone_number
            else:
                # The adapter may use only terminal metadata. PAN, PIN, CVV and
                # track data are intentionally not accepted by this API.
                terminals = adapter_config.get("terminals", {})
                if not isinstance(terminals, dict) or (terminals and device_id not in terminals):
                    raise ValidationError("No approved card terminal is mapped to this POS device.")
                terminal_id = terminals.get(device_id, adapter_config.get("terminal_id", ""))
                if not isinstance(terminal_id, str):
                    raise ValidationError("The configured card terminal identifier is invalid.")
                context["terminal_id"] = terminal_id
            tender = PaymentTenderService.allocate(
                intent=intent,
                tender_type=tender_type,
                provider=provider_code,
                allocated_amount=amount,
                actor=actor,
                idempotency_key=idempotency_key,
                register_id=authority.register.code,
                register_session=authority.session,
                operator_shift=authority.operator_shift,
            )
            tender.status = "PENDING"
            tender.save(update_fields=["status"])
            attempt = PaymentAttempt.all_objects.create(
                tenant=source.tenant,
                payment_tender=tender,
                provider=provider_code,
                attempt_number=1,
                request_reference=f"CHK-{tender.pk.hex}",
                requested_amount=amount,
                request_payload_hash=command_hash,
                status="STARTED",
                idempotency_key=f"checkout-attempt:{idempotency_key}",
            )
        # The attempt is committed BEFORE external I/O. A timeout or process
        # crash leaves an observable pending attempt, never an invitation to charge again.
        # A connector exception is intentionally allowed to reach the API as an
        # unknown outcome. The committed attempt remains STARTED, and the till's
        # durable journal blocks a new collection until it checks this command.
        result = adapter.initiate(attempt=attempt, context=context)
        with transaction.atomic():
            lock_intent(tender.payment_intent)
            attempt = PaymentAttempt.all_objects.select_for_update().get(pk=attempt.pk)
            # A signed callback can arrive before the initiation response. Its
            # definitive outcome takes precedence over this acknowledgement.
            if attempt.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return cls.snapshot(source=source, actor=actor)
            provider_reference = str(result.provider_reference or "")
            invalid_reference = len(provider_reference) > 255
            if not invalid_reference:
                attempt.provider_reference = provider_reference
            attempt.failure_code = result.failure_code[:64]
            attempt.failure_reason = result.failure_reason[:300]
            attempt.status = "STARTED" if invalid_reference else "ACCEPTED" if result.accepted is True else "STARTED" if result.failure_code in {
                "PROVIDER_UNAVAILABLE", "UNKNOWN_OUTCOME"
            } else "FAILED"
            if invalid_reference:
                attempt.failure_code = "UNKNOWN_OUTCOME"
                attempt.failure_reason = "Provider reference is invalid. Reconcile before another collection."
            attempt.save()
            if attempt.status == "FAILED":
                tender.status = "FAILED"
                tender.save(update_fields=["status"])
        return cls.snapshot(source=source, actor=actor)

    @classmethod
    def query_provider(cls, *, source, actor):
        from apps.prescription.payment_connections import provider_adapter
        from apps.prescription.payment_models import PaymentAttempt
        from apps.prescription.payment_orchestration import PaymentEventService

        _require_capability(actor, source.tenant_id, "pos.payment.status.view")
        intent = cls.intent(source)
        if not intent:
            return cls.snapshot(source=source, actor=actor)
        for attempt in PaymentAttempt.all_objects.filter(
            payment_tender__payment_intent=intent,
            status__in=["STARTED", "ACCEPTED"],
        ):
            if not attempt.provider_reference and attempt.provider == "MPESA":
                continue
            try:
                adapter = provider_adapter(
                    tenant=source.tenant, branch=source.branch, provider_code=attempt.provider
                )
            except (ValidationError, ValueError):
                # Tenant config may be temporarily unavailable. Keep the attempt
                # pending and visible for an operator to resolve.
                continue
            try:
                event = adapter.query_status(attempt=attempt)
            except Exception:  # noqa: BLE001 - status transport failure is not payment failure
                continue
            if event and event.status != "PENDING":
                PaymentEventService.apply(
                    tenant=source.tenant, provider_code=attempt.provider, event=event, authenticated=True,
                    settlement_source="PROVIDER_QUERY",
                )
        # A callback may already have settled the ledger before this query.
        # Completing from the settled fact also recovers a failed stock handover
        # without issuing a second provider request or a second receipt.
        intent.refresh_from_db()
        completion_error = ""
        if intent.status == "SETTLED":
            from apps.prescription.payment_models import PaymentSettlement

            settlement = PaymentSettlement.all_objects.filter(
                payment_tender__payment_intent=intent
            ).order_by("-settled_at").first()
            if settlement:
                try:
                    with transaction.atomic():
                        cls.complete(
                            source=source, actor=actor, intent=intent, settlement=settlement, device_id=intent.device_id
                        )
                except ValidationError:
                    completion_error = "Payment is recorded. Stock or register context needs review before sale completion. Do not collect again."
        source.refresh_from_db()
        result = cls.snapshot(source=source, actor=actor)
        result["completion_error"] = completion_error
        return result
