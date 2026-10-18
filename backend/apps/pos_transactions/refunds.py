"""Receipt-linked, independently approved retail refunds. Never reopen a sale."""
from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.provisioning import _is_cold_chain, _is_controlled
from apps.pricing.resolution import money
from apps.workflows.service import emit_event

from .models import (
    PosTransaction,
    PosTransactionLine,
    RetailCashReceipt,
    RetailCashRefund,
    RetailRefundLine,
    RetailRefundRequest,
)
from .services import PosRetailService, _require

logger = logging.getLogger(__name__)
RESERVED = [RetailRefundRequest.Status.REQUESTED, RetailRefundRequest.Status.APPROVED, RetailRefundRequest.Status.COMPLETED]


class RetailRefundService:
    @staticmethod
    def _sale(tenant, transaction_id):
        # Refund keys are tenant-wide. Serialize this low-volume exception
        # workflow before locking the sale, preventing simultaneous distinct
        # receipts from both consuming one key and leaking an IntegrityError.
        tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        sale = PosTransaction.all_objects.select_for_update().select_related("branch").filter(tenant=tenant, pk=transaction_id).first()
        if sale is None or sale.state != PosTransaction.State.COMPLETED:
            raise ValidationError("A completed retail sale with an original cash receipt is required.")
        receipt = RetailCashReceipt.all_objects.filter(tenant=tenant, transaction=sale).first()
        if receipt is None:
            raise ValidationError("The original retail cash receipt is missing.")
        return sale, receipt

    @staticmethod
    def _audit(request, actor, action, metadata=None):
        AuditEvent.all_objects.create(tenant_id=request.tenant_id, actor=actor, action=action,
                                     model_name="RetailRefundRequest", object_id=str(request.pk),
                                     outcome="SUCCESS", metadata=metadata or {})

    @staticmethod
    def _holding_location(tenant, sale, location_id, lines):
        if not any(line["return_to_stock"] for line in lines):
            if location_id:
                raise ValidationError("A return location is only valid when physical stock is received.")
            return None
        location = InventoryLocation.all_objects.filter(tenant=tenant, branch=sale.branch, pk=location_id,
                                                        status=InventoryLocation.Status.ACTIVE,
                                                        location_type=InventoryLocation.LocationType.QUARANTINE,
                                                        quarantine_capability=True).first()
        if location is None:
            raise ValidationError("Physical returns require an active same-branch quarantine holding location.")
        return location

    @classmethod
    @transaction.atomic
    def request(cls, *, tenant, transaction_id, actor, device_id, reason, lines, idempotency_key, return_location_id=None):
        _require(actor, tenant.pk, "pos.refund.request")
        reason = reason.strip()
        key = idempotency_key.strip()
        if not reason or not key or not lines:
            raise ValidationError("A reason, refund lines and stable idempotency key are required.")
        sale, receipt = cls._sale(tenant, transaction_id)
        fingerprint = hashlib.sha256(json.dumps({"sale": str(sale.pk), "actor": str(actor.pk), "device": device_id,
            "reason": reason, "location": str(return_location_id or ""), "lines": [
                {"line": str(row["line_id"]), "quantity": str(Decimal(str(row["quantity"])).normalize()),
                 "return": bool(row["return_to_stock"]), "batch": str(row.get("inventory_batch_id") or "")} for row in lines
            ]}, sort_keys=True).encode()).hexdigest()
        existing = RetailRefundRequest.all_objects.filter(tenant=tenant, idempotency_key=key).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ValidationError("This refund request key has already been used with different details.")
            return existing
        PosRetailService._authority(tenant=tenant, branch=sale.branch, actor=actor, device_id=device_id)
        location = cls._holding_location(tenant, sale, return_location_id, lines)
        seen, prepared, total = set(), [], Decimal("0.00")
        for row in lines:
            line_id, qty = row["line_id"], Decimal(str(row["quantity"]))
            if str(line_id) in seen or not qty.is_finite() or qty <= 0 or qty.as_tuple().exponent < -4:
                raise ValidationError("Specify each original line once with a positive quantity of at most four decimal places.")
            seen.add(str(line_id))
            original = PosTransactionLine.all_objects.filter(tenant=tenant, transaction=sale, pk=line_id).select_related("sku").first()
            if original is None:
                raise ValidationError("Refund line does not belong to the original receipt.")
            used = RetailRefundLine.all_objects.filter(tenant=tenant, original_line=original, refund_request__status__in=RESERVED)
            prior = used.aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
            remaining = original.quantity - (prior["quantity"] or 0)
            if qty > remaining:
                raise ValidationError("Refund quantity exceeds the unrefunded original sale quantity (including pending requests).")
            amount = (original.line_total - (prior["amount"] or 0)) if qty == remaining else money(original.line_total * qty / original.quantity)
            if amount < 0:
                raise ValidationError("Refund exceeds the unrefunded original line value.")
            batch = None
            if row["return_to_stock"]:
                if not original.sku.stock_tracking_required:
                    raise ValidationError("A non-stock item cannot be received into inventory.")
                batch = InventoryBatch.all_objects.filter(tenant=tenant, sku=original.sku, pk=row.get("inventory_batch_id")).first()
                if batch is None:
                    raise ValidationError("Confirm the returned item's actual original sale batch.")
                issued = InventoryLedgerEntry.all_objects.filter(tenant=tenant, source_document_type="POS_RETAIL_TRANSACTION",
                    source_document_id=str(sale.pk), source_line_id=str(original.pk), inventory_batch=batch, entry_type="ISSUE").aggregate(qty=Sum("base_quantity_delta"))["qty"] or 0
                returned = used.filter(return_to_stock=True, inventory_batch=batch).aggregate(qty=Sum("quantity"))["qty"] or 0
                if qty > -issued - returned:
                    raise ValidationError("The confirmed batch quantity exceeds what was issued on this receipt.")
                if _is_controlled(original.sku) and not location.controlled_drug_capability:
                    raise ValidationError("Controlled stock requires a controlled quarantine holding location.")
                if _is_cold_chain(original.sku) and not location.cold_chain_capability:
                    raise ValidationError("Cold-chain stock requires a cold-chain quarantine holding location.")
            elif row.get("inventory_batch_id"):
                raise ValidationError("A batch is only valid for physical stock returns.")
            prepared.append((original, qty, amount, row["return_to_stock"], batch))
            total += amount
        if total <= 0 or total > receipt.amount:
            raise ValidationError("The refundable cash amount must be positive and not exceed the original receipt.")
        from apps.prescription.payment_models import PaymentTender
        tenders = list(PaymentTender.all_objects.filter(tenant=tenant, payment_intent__retail_transaction=sale).order_by("created_at"))
        prior_plans = RetailRefundRequest.all_objects.filter(tenant=tenant, transaction=sale, status__in=RESERVED).values_list("payment_plan", flat=True)
        used_by_tender = {}
        for plan in prior_plans:
            for part in plan:
                used_by_tender[part["tender_id"]] = used_by_tender.get(part["tender_id"], Decimal(0)) + Decimal(part["amount"])
        outstanding = total
        payment_plan = []
        for tender in sorted(tenders, key=lambda t: t.tender_type != "CASH"):
            available = tender.effective_settled - used_by_tender.get(str(tender.pk), Decimal(0))
            amount = min(outstanding, available)
            if amount > 0:
                payment_plan.append({"tender_id": str(tender.pk), "tender_type": tender.tender_type, "provider": tender.provider, "amount": str(amount)})
                outstanding -= amount
        if tenders and outstanding > 0:
            raise ValidationError("The refund exceeds unrefunded original payment value.")
        if not tenders:
            payment_plan = [{"tender_id": "legacy-cash", "tender_type": "CASH", "amount": str(total)}]
        request = RetailRefundRequest.all_objects.create(tenant=tenant, transaction=sale, original_receipt=receipt,
            reason=reason, amount=total, currency=receipt.currency, return_location=location, requested_by=actor,
            idempotency_key=key, request_fingerprint=fingerprint, payment_plan=payment_plan)
        for original, qty, amount, physical, batch in prepared:
            RetailRefundLine.all_objects.create(tenant=tenant, refund_request=request, original_line=original,
                quantity=qty, amount=amount, return_to_stock=physical, inventory_batch=batch)
        cls._audit(request, actor, "RETAIL_REFUND_REQUESTED", {"amount": str(total), "original_receipt": receipt.receipt_number})
        return request

    @classmethod
    @transaction.atomic
    def review(cls, *, tenant, transaction_id, request_id, actor, approve, reason=""):
        _require(actor, tenant.pk, "pos.refund.approve")
        cls._sale(tenant, transaction_id)
        request = RetailRefundRequest.all_objects.select_for_update().filter(tenant=tenant, transaction_id=transaction_id, pk=request_id).first()
        if request is None:
            raise ValidationError("Refund request not found for this receipt.")
        if actor.pk == request.requested_by_id:
            raise ValidationError("An independent supervisor must review this refund request.")
        desired = RetailRefundRequest.Status.APPROVED if approve else RetailRefundRequest.Status.REJECTED
        if request.status == desired and request.approved_by_id == actor.pk:
            return request
        if request.status != RetailRefundRequest.Status.REQUESTED:
            raise ValidationError("Only a pending refund request can be reviewed.")
        if not approve and not reason.strip():
            raise ValidationError("Explain why this refund is rejected.")
        request.status, request.approved_by, request.reviewed_at, request.review_reason = desired, actor, timezone.now(), reason.strip()
        request.save(update_fields=["status", "approved_by", "reviewed_at", "review_reason", "updated_at"])
        cls._audit(request, actor, "RETAIL_REFUND_APPROVED" if approve else "RETAIL_REFUND_REJECTED")
        return request

    @classmethod
    @transaction.atomic
    def execute_cash(cls, *, tenant, transaction_id, request_id, actor, device_id, idempotency_key, payment_references=None):
        _require(actor, tenant.pk, "pos.refund.cash.execute")
        key = idempotency_key.strip()
        if not key:
            raise ValidationError("A stable cash refund idempotency key is required.")
        sale, original_receipt = cls._sale(tenant, transaction_id)
        # Tenant/sale anchors above and this request remain locked. Optional
        # return custody/reviewer joins cannot be FOR UPDATE targets on PostgreSQL.
        request = RetailRefundRequest.all_objects.select_for_update(of=("self",)).select_related("return_location", "approved_by").filter(
            tenant=tenant, transaction=sale, pk=request_id).first()
        if request is None:
            raise ValidationError("Refund request not found for this receipt.")
        keyed = RetailCashRefund.all_objects.filter(tenant=tenant, idempotency_key=key).first()
        existing = RetailCashRefund.all_objects.filter(tenant=tenant, refund_request=request).first()
        if keyed or existing:
            receipt = existing or keyed
            if receipt.refund_request_id == request.pk and receipt.idempotency_key == key and receipt.created_by_id == actor.pk and receipt.device_id == device_id:
                for part in receipt.payment_plan:
                    if part["tender_type"] == "CARD" and str((payment_references or {}).get(part["tender_id"], "")).strip() != part.get("reference", ""):
                        raise ValidationError("This refund retry has different terminal approval details.")
                return receipt
            raise ValidationError("This refund or idempotency key has already been completed with different details.")
        if request.status != RetailRefundRequest.Status.APPROVED or request.approved_by_id == request.requested_by_id:
            raise ValidationError("An independently approved refund request is required before handing cash back.")
        if not request.approved_by or not request.approved_by.has_capability("pos.refund.approve", tenant_id=tenant.pk):
            raise ValidationError("The refund approver is no longer active or authorised; an active independent approval is required.")
        payment_references = payment_references or {}
        plan = request.payment_plan or [{"tender_id": "legacy-cash", "tender_type": "CASH", "amount": str(request.amount)}]
        cash_amount = sum((Decimal(part["amount"]) for part in plan if part["tender_type"] == "CASH"), Decimal(0))
        completed_plan = []
        used_references = set()
        for part in plan:
            reference = str(payment_references.get(part["tender_id"], "")).strip()
            if part["tender_type"] == "MPESA":
                raise ValidationError("M-PESA refunds require a verified Daraja reversal integration; cash cannot substitute for a mobile payment reversal.")
            if part["tender_type"] == "CARD":
                from apps.prescription.payment_connections import require_external_card_refund
                from apps.prescription.payment_models import PaymentTender

                original_tender = PaymentTender.all_objects.filter(
                    tenant=tenant, pk=part["tender_id"], payment_intent__retail_transaction=sale
                ).first()
                if original_tender is None:
                    raise ValidationError("The original card payment evidence is unavailable.")
                require_external_card_refund(tenant=tenant, branch=sale.branch, provider_code=original_tender.provider)
                if not reference or len(reference) > 128:
                    raise ValidationError("Record the external terminal refund approval reference for each card portion.")
                if reference in used_references:
                    raise ValidationError("Record a distinct terminal approval for each card refund portion.")
                used_references.add(reference)
                prior_refunds = RetailCashRefund.all_objects.filter(tenant=tenant).values_list("payment_plan", flat=True)
                if any(reference == item.get("reference") for previous in prior_refunds for item in previous if item.get("tender_type") == "CARD"):
                    raise ValidationError("This terminal refund approval reference has already been recorded.")
            completed_plan.append({**part, "reference": reference})
        authority = PosRetailService._authority(tenant=tenant, branch=sale.branch, actor=actor, device_id=device_id)
        if request.currency != authority.register.currency:
            raise ValidationError("Refund currency does not match the active register.")
        from apps.pos_shift.cash_control import CashControlService
        if CashControlService.expected_cash(session=authority.session).expected < cash_amount:
            raise ValidationError("The active drawer has insufficient expected cash for this refund; use an authorised cash-in or funded register.")
        lines = list(RetailRefundLine.all_objects.filter(tenant=tenant, refund_request=request).select_related("original_line__sku", "inventory_batch"))
        location = request.return_location
        if any(line.return_to_stock for line in lines) and (not location or location.status != "ACTIVE" or not location.quarantine_capability):
            raise ValidationError("The return quarantine holding location is no longer available.")
        snapshot = []
        for line in lines:
            if line.return_to_stock:
                # Batch identity remains the original issue fact. Returned custody,
                # not a global batch-quality edit, prevents these goods being sold.
                if _is_controlled(line.original_line.sku) and not location.controlled_drug_capability:
                    raise ValidationError("Controlled quarantine capability is required.")
                if _is_cold_chain(line.original_line.sku) and not location.cold_chain_capability:
                    raise ValidationError("Cold-chain quarantine capability is required.")
                InventoryLedgerService.post_entry(tenant=tenant, branch=sale.branch, location=location,
                    sku=line.original_line.sku, inventory_batch=line.inventory_batch, entry_type="RETURN_IN",
                    quantity_delta=line.quantity, base_quantity_delta=line.quantity, unit=line.original_line.unit,
                    effective_timestamp=timezone.now(), source_document_type="POS_RETAIL_REFUND", source_document_id=str(request.pk),
                    source_line_id=str(line.pk), idempotency_key=f"retail-refund-return:{line.pk}", actor=actor,
                    reason_code="CUSTOMER_RETURN_QUARANTINE", notes=request.reason)
            snapshot.append({"original_line_id": str(line.original_line_id), "description": line.original_line.description_snapshot,
                "sku_code": line.original_line.sku.sku_code, "quantity": str(line.quantity), "unit": line.original_line.unit,
                "amount": str(line.amount), "return_to_stock": line.return_to_stock,
                "batch_number": line.inventory_batch.manufacturer_batch_number if line.inventory_batch else "",
                "return_location": location.location_code if line.return_to_stock else "",
                "disposition": "QUARANTINE_PENDING_QUALITY_REVIEW" if line.return_to_stock else "FINANCIAL_ONLY_NO_STOCK_RECEIVED"})
        receipt = RetailCashRefund.all_objects.create(tenant=tenant, refund_request=request, original_receipt=original_receipt,
            register=authority.register, register_session=authority.session, operator_shift=authority.operator_shift,
            device_id=device_id, amount=request.amount, cash_amount=cash_amount, payment_plan=completed_plan, currency=request.currency, lines_snapshot=snapshot,
            created_by=actor, approved_by=request.approved_by, idempotency_key=key)
        request.status = RetailRefundRequest.Status.COMPLETED
        request.save(update_fields=["status", "updated_at"])
        from apps.prescription.fiscal import FiscalService
        FiscalService.enqueue(source=receipt)
        cls._audit(request, actor, "RETAIL_CASH_REFUND_COMPLETED", {"receipt": receipt.refund_number, "amount": str(receipt.amount)})

        try:
            from apps.prescription.pos_printing_services import PosPrintDocumentService
            with transaction.atomic():
                PosPrintDocumentService.issue_retail_refund(receipt=receipt, actor=actor)
        except Exception:
            logger.exception("Could not queue retail refund receipt.", extra={"refund_id": str(receipt.pk)})
        emit_event(tenant_id=str(tenant.pk), aggregate_type="RetailCashRefund", aggregate_id=str(receipt.pk),
                   event_type="RetailCashRefundCompleted", payload={"original_receipt_id": str(original_receipt.pk),
                   "refund_number": receipt.refund_number, "amount": str(receipt.amount), "currency": receipt.currency,
                   "register_session_id": str(receipt.register_session_id)})
        return receipt
