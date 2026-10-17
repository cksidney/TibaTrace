"""Return money from an unfinished retail checkout without issuing stock."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import InventoryReservation
from apps.inventory.services import InventoryReservationService
from apps.pos_shift.authority import RegisterAuthorityService
from apps.pos_shift.cash_control import CashControlService
from apps.prescription.payment_models import PaymentReversal, PaymentSettlement, PaymentTender
from apps.prescription.payment_services import PaymentStateProjectionService
from apps.prescription.services.clinical_dispensing import _require_capability


class CheckoutVoidService:
    @staticmethod
    @transaction.atomic
    def run(*, source, actor, device_id, approve, reason, references):
        from apps.prescription.checkout import CheckoutService
        _require_capability(actor, source.tenant_id, 'pos.refund.approve' if approve else 'pos.refund.request')
        source = type(source).all_objects.select_for_update().get(pk=source.pk, tenant_id=source.tenant_id)
        intent = CheckoutService.intent(source)
        if source._meta.model_name != 'postransaction' or not intent or intent.device_id != device_id:
            raise ValidationError('An unfinished retail checkout on its original device is required.')
        if source.state == 'VOIDED' and approve:
            return CheckoutService.snapshot(source=source, actor=actor)
        if source.state != 'PAYMENT_IN_PROGRESS':
            raise ValidationError('Completed sales use the original-receipt refund workflow.')
        if PaymentTender.all_objects.filter(payment_intent=intent, status='PENDING').exists():
            raise ValidationError('Resolve all pending provider requests before voiding a checkout.')
        if not approve:
            if not reason.strip():
                raise ValidationError('Explain why this unfinished payment must be returned.')
            settlements = PaymentSettlement.all_objects.filter(payment_tender__payment_intent=intent)
            if not settlements.exists():
                raise ValidationError('No collected value exists to return.')
            for settlement in settlements:
                PaymentReversal.all_objects.get_or_create(tenant=source.tenant, idempotency_key=f'checkout-void:{settlement.pk}',
                    defaults={'settlement': settlement, 'amount': settlement.amount, 'reason': reason.strip(), 'requested_by': actor})
            PaymentStateProjectionService.project(intent=intent)
        else:
            reversals = list(PaymentReversal.all_objects.select_for_update().filter(settlement__payment_tender__payment_intent=intent, status='REQUESTED').select_related('settlement__payment_tender'))
            if not reversals or any(item.requested_by_id == actor.pk for item in reversals):
                raise ValidationError('A different authorised supervisor must confirm the original-method return.')
            authority = RegisterAuthorityService.resolve_for_transaction(tenant=source.tenant, branch=source.branch, actor=actor, device_id=device_id)
            if authority.session.pk != source.register_session_id:
                raise ValidationError('Return an unfinished payment on its original open register session.')
            cash = sum((item.amount for item in reversals if item.settlement.payment_tender.tender_type == 'CASH'), Decimal(0))
            if CashControlService.expected_cash(session=authority.session).expected < cash:
                raise ValidationError('The original drawer has insufficient cash for this return.')
            seen = set()
            for item in reversals:
                method = item.settlement.payment_tender.tender_type
                reference = str(references.get(str(item.pk), '')).strip()
                if method == 'MPESA':
                    raise ValidationError('Verified Daraja reversal setup is required to return M-PESA payments.')
                if method == 'CARD':
                    if not reference or len(reference) > 128 or reference in seen or PaymentReversal.all_objects.filter(tenant=source.tenant, provider_reference=reference, status='COMPLETED').exists():
                        raise ValidationError('Each card return needs its distinct terminal refund approval reference.')
                    seen.add(reference)
                item.provider_reference, item.approved_by, item.status, item.completed_at = reference, actor, 'COMPLETED', timezone.now()
                item.save()
            for tender in PaymentTender.all_objects.filter(payment_intent=intent):
                tender.reversed_amount = tender.settled_amount
                tender.status = 'REVERSED' if tender.settled_amount else 'CANCELLED'
                tender.save(update_fields=['reversed_amount', 'status'])
            PaymentStateProjectionService.project(intent=intent)
            for reservation in InventoryReservation.all_objects.filter(tenant=source.tenant, source_document=str(source.pk), purpose='POS_CHECKOUT', status='ALLOCATED'):
                InventoryReservationService.release_reservation(reservation=reservation, actor=actor)
            source.state, source.cancellation_reason, source.cancelled_at = 'VOIDED', reversals[0].reason, timezone.now()
            source.save(update_fields=['state', 'cancellation_reason', 'cancelled_at', 'updated_at'])
            from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
            from apps.prescription.pos_printing_services import _hash_snapshot
            number = f'VOID-{source.transaction_number}'
            snapshot = {'document_type': 'REVERSAL_RECEIPT', 'document_number': number, 'issued_at': source.cancelled_at.isoformat(),
                        'lines': [], 'payment': {'currency': source.currency, 'refund_amount': str(sum((item.amount for item in reversals), Decimal(0))),
                        'tenders': [{'tender_type': item.settlement.payment_tender.tender_type, 'amount': str(item.amount), 'reference': item.provider_reference} for item in reversals]},
                        'disclaimer': 'Unfinished retail payment returned; no goods issued. Internal return receipt.'}
            document = PosPrintDocument.all_objects.create(tenant=source.tenant, document_type='REVERSAL_RECEIPT', document_number=number,
                snapshot=snapshot, document_hash=_hash_snapshot(snapshot), register_session=source.register_session, created_by=actor)
            PosPrintJob.all_objects.create(tenant=source.tenant, document=document, branch=source.branch, device_id=device_id,
                requested_by=actor, transport='SIMULATOR', idempotency_key=f'checkout-void-print:{intent.pk}')
        from apps.audit.models import AuditEvent
        AuditEvent.all_objects.create(tenant=source.tenant, actor=actor, action='CHECKOUT_VOID_COMPLETED' if approve else 'CHECKOUT_VOID_REQUESTED', model_name='PosTransaction', object_id=str(source.pk), outcome='SUCCESS', metadata={'intent_id': str(intent.pk), 'device_id': device_id})
        return CheckoutService.snapshot(source=source, actor=actor)
