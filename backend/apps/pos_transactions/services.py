from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventory.models import (
    BarcodeMaster,
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
)
from apps.inventory.services import FEFOAllocationService, InventoryLedgerService
from apps.medicines.models import BranchAssortment, CommercialSKU, ProductIdentifier
from apps.pos_shift.authority import RegisterAuthority, RegisterAuthorityService
from apps.pricing.catalogue import PriceCatalogue
from apps.pricing.resolution import PricingContext, PricingError, money
from apps.workflows.service import emit_event

from .models import PosTransaction, PosTransactionInventoryContext, PosTransactionLine, RetailCashReceipt

logger = logging.getLogger(__name__)


def _require(actor, tenant_id, capability: str) -> None:
    if not actor or not actor.has_capability(capability, tenant_id=tenant_id):
        raise PermissionDenied(f"Capability {capability} is required.")


@dataclass(frozen=True)
class RetailCatalogueItem:
    sku: CommercialSKU
    available_quantity: Decimal
    stock_state: str
    resolved_price: object


class PosRetailService:
    @staticmethod
    def _authority(*, tenant, branch, actor, device_id: str) -> RegisterAuthority:
        return RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
        )

    @staticmethod
    def _store(*, tenant, branch, store_id) -> InventoryLocation:
        store = InventoryLocation.all_objects.filter(
            tenant=tenant,
            branch=branch,
            pk=store_id,
            status=InventoryLocation.Status.ACTIVE,
        ).first()
        if store is None:
            raise ValidationError("An active store for this branch is required.")
        return store

    @staticmethod
    def _catalogue_item(*, tenant, branch, store, sku, quantity, customer=None) -> RetailCatalogueItem:
        assortment = BranchAssortment.all_objects.filter(
            tenant=tenant,
            location=branch,
            sku=sku,
            is_sellable=True,
        ).first()
        if assortment is None:
            raise ValidationError("This item is not in the sellable branch assortment.")
        if sku.status != CommercialSKU.STATUS_ACTIVE or not sku.is_saleable:
            raise ValidationError("This item is not saleable.")

        quantity = Decimal(str(quantity))
        context = PricingContext(
            tenant_id=str(tenant.pk),
            branch_id=str(branch.pk),
            sku_id=str(sku.pk),
            service_date=timezone.localdate(),
            quantity=quantity,
            currency="KES",
            customer_id=str(customer.pk) if customer else None,
        )
        try:
            resolved = PriceCatalogue.price(context=context)
        except PricingError as exc:
            raise ValidationError(str(exc)) from exc

        availability = (
            InventoryBalance.all_objects.filter(
                tenant=tenant,
                branch=branch,
                location=store,
                sku=sku,
                inventory_batch__isnull=False,
                available__gt=0,
                expiry_status="NORMAL",
            )
            .filter(
                inventory_batch__quality_status=InventoryBatch.QualityStatus.RELEASED,
                inventory_batch__recall_status=InventoryBatch.RecallStatus.NONE,
                inventory_batch__expiry_date__gt=timezone.localdate(),
            )
            .aggregate(total=Sum("available"))["total"]
            or Decimal("0.0000")
        )
        available = Decimal(str(availability))
        if not sku.stock_tracking_required:
            stock_state = PosTransactionInventoryContext.StockState.NOT_TRACKED
        elif available >= quantity:
            stock_state = PosTransactionInventoryContext.StockState.IN_STOCK
        elif available > 0:
            stock_state = PosTransactionInventoryContext.StockState.INSUFFICIENT
        else:
            stock_state = PosTransactionInventoryContext.StockState.OUT_OF_STOCK
        return RetailCatalogueItem(
            sku=sku,
            available_quantity=available,
            stock_state=stock_state,
            resolved_price=resolved,
        )

    @classmethod
    @transaction.atomic
    def create_draft(cls, *, tenant, branch, store_id, actor, device_id: str, customer=None, patient=None):
        _require(actor, tenant.pk, "pos.transaction.create")
        authority = cls._authority(tenant=tenant, branch=branch, actor=actor, device_id=device_id)
        store = cls._store(tenant=tenant, branch=branch, store_id=store_id)
        if customer is not None and customer.tenant_id != tenant.pk:
            raise ValidationError("The selected customer belongs to a different tenant.")
        if patient is not None and patient.tenant_id != tenant.pk:
            raise ValidationError("The selected patient belongs to a different tenant.")
        return PosTransaction.all_objects.create(
            tenant=tenant,
            branch=branch,
            store=store,
            register=authority.register,
            register_session=authority.session,
            operator_shift=authority.operator_shift,
            business_day=authority.business_day,
            operator=actor,
            device_id=device_id,
            customer=customer,
            patient=patient,
            currency=authority.register.currency,
        )

    @classmethod
    def search_catalogue(cls, *, tenant, branch, store_id, actor, device_id: str, query: str, customer=None):
        _require(actor, tenant.pk, "pos.transaction.create")
        cls._authority(tenant=tenant, branch=branch, actor=actor, device_id=device_id)
        store = cls._store(tenant=tenant, branch=branch, store_id=store_id)
        term = query.strip()
        if not term:
            return []
        skus = (
            CommercialSKU.all_objects.filter(
                tenant=tenant,
                status=CommercialSKU.STATUS_ACTIVE,
                is_saleable=True,
                branch_assortments__tenant=tenant,
                branch_assortments__location=branch,
                branch_assortments__is_sellable=True,
            )
            .filter(Q(display_name__icontains=term) | Q(sku_code__icontains=term) | Q(default_barcode__icontains=term))
            .distinct()
            .order_by("display_name")[:30]
        )
        items = []
        for sku in skus:
            try:
                items.append(cls._catalogue_item(
                    tenant=tenant,
                    branch=branch,
                    store=store,
                    sku=sku,
                    quantity=Decimal("1"),
                    customer=customer,
                ))
            except ValidationError:
                continue
        return items

    @classmethod
    def resolve_barcode(cls, *, tenant, barcode: str) -> CommercialSKU:
        code = barcode.strip()
        if not code:
            raise ValidationError("Enter or scan a barcode.")
        sku_ids = list(
            BarcodeMaster.all_objects.filter(tenant=tenant, barcode=code, is_active=True)
            .values_list("sku_id", flat=True)
        )
        if not sku_ids:
            sku_ids = list(
                CommercialSKU.all_objects.filter(tenant=tenant, default_barcode=code)
                .values_list("pk", flat=True)
            )
        if not sku_ids:
            sku_ids = list(
                ProductIdentifier.objects.filter(entity_type="SKU", value=code)
                .values_list("entity_id", flat=True)
            )
        sku_ids = list(dict.fromkeys(sku_ids))
        if not sku_ids:
            raise ValidationError("The scanned barcode is not registered in this tenant catalogue.")
        if len(sku_ids) != 1:
            raise ValidationError("The scanned barcode maps to more than one product. Correct the barcode mapping.")
        sku = CommercialSKU.all_objects.filter(tenant=tenant, pk=sku_ids[0]).first()
        if sku is None:
            raise ValidationError("The scanned barcode does not map to a tenant product.")
        return sku

    @classmethod
    @transaction.atomic
    def add_line(cls, *, tenant, transaction_id, actor, device_id: str, sku_id, quantity, scan_source="SEARCH"):
        # Guest sales have no customer row. Preserve the mandatory transaction,
        # branch and store locks without locking that nullable pricing join.
        transaction_record = (
            PosTransaction.all_objects.select_for_update(of=("self", "branch", "store"))
            .select_related("branch", "store", "customer")
            .filter(tenant=tenant, pk=transaction_id)
            .first()
        )
        if transaction_record is None:
            raise ValidationError("POS transaction not found.")
        _require(actor, tenant.pk, "pos.transaction.create")
        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        cls._validate_editable_transaction(transaction_record, authority)
        sku = CommercialSKU.all_objects.filter(tenant=tenant, pk=sku_id).first()
        if sku is None:
            raise ValidationError("Product not found in this tenant catalogue.")
        requested_quantity = Decimal(str(quantity))
        if requested_quantity <= 0:
            raise ValidationError("Line quantity must be greater than zero.")
        existing = PosTransactionLine.all_objects.select_for_update().filter(
            tenant=tenant, transaction=transaction_record, sku=sku
        ).first()
        resulting_quantity = requested_quantity + (existing.quantity if existing else Decimal("0"))
        item = cls._catalogue_item(
            tenant=tenant,
            branch=transaction_record.branch,
            store=transaction_record.store,
            sku=sku,
            quantity=resulting_quantity,
            customer=transaction_record.customer,
        )
        cls._require_stock(item=item, sku=sku, quantity=resulting_quantity)
        unit_price = money(item.resolved_price.unit_price)
        line_total = money(unit_price * resulting_quantity)
        snapshot = {
            "unit_price": str(unit_price),
            "source": item.resolved_price.source,
            "source_reference": item.resolved_price.reference,
            "context_hash": item.resolved_price.context_hash,
            "considered": list(item.resolved_price.considered),
            "tax_inclusive": item.resolved_price.tax_inclusive,
        }
        if existing is None:
            line = PosTransactionLine.all_objects.create(
                tenant=tenant,
                transaction=transaction_record,
                sku=sku,
                description_snapshot=sku.display_name,
                unit=sku.package_definition.unit_of_measure,
                quantity=resulting_quantity,
                unit_price=unit_price,
                line_total=line_total,
                currency=transaction_record.currency,
                price_snapshot=snapshot,
                scan_source=scan_source,
            )
        else:
            existing.quantity = resulting_quantity
            existing.unit_price = unit_price
            existing.line_total = line_total
            existing.price_snapshot = snapshot
            existing.scan_source = scan_source
            existing.save(update_fields=[
                "quantity", "unit_price", "line_total", "price_snapshot", "scan_source", "updated_at",
            ])
            line = existing
        cls._update_inventory_context(line=line, item=item, store=transaction_record.store)
        cls._recalculate(transaction_record)
        return line

    @classmethod
    @transaction.atomic
    def set_quantity(cls, *, tenant, transaction_id, line_id, actor, device_id: str, quantity):
        transaction_record = PosTransaction.all_objects.select_for_update(of=("self", "branch", "store")).select_related(
            "branch", "store", "customer"
        ).filter(tenant=tenant, pk=transaction_id).first()
        line = PosTransactionLine.all_objects.select_for_update().filter(
            tenant=tenant, transaction=transaction_record, pk=line_id
        ).select_related("sku").first()
        if transaction_record is None or line is None:
            raise ValidationError("POS transaction line not found.")
        _require(actor, tenant.pk, "pos.transaction.create")
        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        cls._validate_editable_transaction(transaction_record, authority)
        requested_quantity = Decimal(str(quantity))
        if requested_quantity <= 0:
            raise ValidationError("Use remove line instead of setting quantity to zero.")
        item = cls._catalogue_item(
            tenant=tenant,
            branch=transaction_record.branch,
            store=transaction_record.store,
            sku=line.sku,
            quantity=requested_quantity,
            customer=transaction_record.customer,
        )
        cls._require_stock(item=item, sku=line.sku, quantity=requested_quantity)
        line.quantity = requested_quantity
        line.unit_price = money(item.resolved_price.unit_price)
        line.line_total = money(line.unit_price * requested_quantity)
        line.price_snapshot = {
            "unit_price": str(line.unit_price),
            "source": item.resolved_price.source,
            "source_reference": item.resolved_price.reference,
            "context_hash": item.resolved_price.context_hash,
            "considered": list(item.resolved_price.considered),
            "tax_inclusive": item.resolved_price.tax_inclusive,
        }
        line.save(update_fields=["quantity", "unit_price", "line_total", "price_snapshot", "updated_at"])
        cls._update_inventory_context(line=line, item=item, store=transaction_record.store)
        cls._recalculate(transaction_record)
        return line

    @classmethod
    @transaction.atomic
    def remove_line(cls, *, tenant, transaction_id, line_id, actor, device_id: str):
        transaction_record = PosTransaction.all_objects.select_for_update().select_related("branch").filter(
            tenant=tenant, pk=transaction_id
        ).first()
        if transaction_record is None:
            raise ValidationError("POS transaction not found.")
        _require(actor, tenant.pk, "pos.transaction.create")
        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        cls._validate_editable_transaction(transaction_record, authority)
        line = PosTransactionLine.all_objects.filter(
            tenant=tenant, transaction=transaction_record, pk=line_id
        ).first()
        if line is None:
            raise ValidationError("POS transaction line not found.")
        line.delete()
        cls._recalculate(transaction_record)

    @classmethod
    @transaction.atomic
    def hold(cls, *, tenant, transaction_id, actor, device_id: str, reason: str = ""):
        _require(actor, tenant.pk, "pos.transaction.hold")
        transaction_record, authority = cls._editable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        if not PosTransactionLine.all_objects.filter(
            tenant=tenant,
            transaction=transaction_record,
        ).exists():
            raise ValidationError("An empty POS transaction cannot be held.")
        transaction_record.state = PosTransaction.State.HELD
        transaction_record.hold_reason = reason.strip()
        transaction_record.held_at = timezone.now()
        transaction_record.save(update_fields=["state", "hold_reason", "held_at", "updated_at"])
        return transaction_record

    @classmethod
    @transaction.atomic
    def resume(cls, *, tenant, transaction_id, actor, device_id: str):
        _require(actor, tenant.pk, "pos.transaction.resume")
        transaction_record, authority = cls._editable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        if transaction_record.state != PosTransaction.State.HELD:
            raise ValidationError("Only a held POS transaction can be resumed.")
        transaction_record.state = PosTransaction.State.DRAFT
        transaction_record.save(update_fields=["state", "updated_at"])
        return transaction_record

    @classmethod
    @transaction.atomic
    def cancel(cls, *, tenant, transaction_id, actor, device_id: str, reason: str):
        _require(actor, tenant.pk, "pos.transaction.cancel")
        transaction_record, authority = cls._cancelable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        if not reason.strip():
            raise ValidationError("Cancelling a POS transaction requires a reason.")
        transaction_record.state = PosTransaction.State.CANCELLED
        transaction_record.cancellation_reason = reason.strip()
        transaction_record.cancelled_at = timezone.now()
        transaction_record.save(update_fields=[
            "state", "cancellation_reason", "cancelled_at", "updated_at",
        ])
        return transaction_record

    @classmethod
    @transaction.atomic
    def ready_for_payment(cls, *, tenant, transaction_id, actor, device_id: str):
        _require(actor, tenant.pk, "pos.payment.cash.accept")
        transaction_record, authority = cls._editable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        lines = list(
            PosTransactionLine.all_objects.filter(
                tenant=tenant,
                transaction=transaction_record,
            ).select_for_update().select_related("sku", "sku__package_definition")
        )
        if not lines:
            raise ValidationError("A POS transaction needs at least one line before payment.")
        for line in lines:
            item = cls._catalogue_item(
                tenant=tenant,
                branch=transaction_record.branch,
                store=transaction_record.store,
                sku=line.sku,
                quantity=line.quantity,
                customer=transaction_record.customer,
            )
            cls._require_stock(item=item, sku=line.sku, quantity=line.quantity)
            line.unit_price = money(item.resolved_price.unit_price)
            line.line_total = money(line.unit_price * line.quantity)
            line.price_snapshot = cls._price_snapshot(item=item, unit_price=line.unit_price)
            line.save(update_fields=["unit_price", "line_total", "price_snapshot", "updated_at"])
            cls._update_inventory_context(line=line, item=item, store=transaction_record.store)
        cls._recalculate(transaction_record)
        transaction_record.state = PosTransaction.State.READY_FOR_PAYMENT
        transaction_record.save(update_fields=["state", "updated_at"])
        return transaction_record

    @classmethod
    @transaction.atomic
    def settle_cash(
        cls,
        *,
        tenant,
        transaction_id,
        actor,
        device_id: str,
        cash_received,
        idempotency_key: str,
        _settled_intent=None,
    ):
        """Atomically accept cash, issue FEFO stock, and complete a retail sale."""
        if _settled_intent is None:
            _require(actor, tenant.pk, "pos.payment.cash.accept")
        key = idempotency_key.strip()
        if not key:
            raise ValidationError("A cash settlement idempotency key is required.")
        received = money(cash_received)
        transaction_record = (
            PosTransaction.all_objects.select_for_update()
            .select_related("branch", "store", "register", "register_session", "operator_shift", "business_day")
            .filter(tenant=tenant, pk=transaction_id)
            .first()
        )
        if transaction_record is None:
            raise ValidationError("POS transaction not found.")

        keyed_receipt = RetailCashReceipt.all_objects.filter(tenant=tenant, idempotency_key=key).first()
        if keyed_receipt and keyed_receipt.transaction_id != transaction_record.pk:
            raise ValidationError("This idempotency key was already used for another retail sale.")
        existing_receipt = RetailCashReceipt.all_objects.filter(
            tenant=tenant, transaction=transaction_record
        ).first()
        if existing_receipt is not None:
            if (
                existing_receipt.idempotency_key == key
                and existing_receipt.cash_received == received
                and existing_receipt.created_by_id == actor.pk
                and transaction_record.device_id == device_id
            ):
                return transaction_record
            raise ValidationError("This retail sale has already been settled.")

        if transaction_record.state != PosTransaction.State.READY_FOR_PAYMENT and not (_settled_intent and transaction_record.state == PosTransaction.State.PAYMENT_IN_PROGRESS):
            raise ValidationError("Only a sale ready for payment can be settled in cash.")
        ledger_tenders = []
        if _settled_intent:
            from apps.prescription.payment_models import PaymentIntent, PaymentTender
            _settled_intent = PaymentIntent.all_objects.select_for_update().get(pk=_settled_intent.pk, tenant=tenant, retail_transaction=transaction_record)
            if _settled_intent.status != "SETTLED" or _settled_intent.effective_settled != transaction_record.total:
                raise ValidationError("The complete sale must be settled in the payment ledger.")
            ledger_tenders = [t for t in PaymentTender.all_objects.filter(tenant=tenant, payment_intent=_settled_intent).exclude(status="CANCELLED") if t.effective_settled > 0]
            from apps.inventory.models import InventoryReservation
            from apps.inventory.services import InventoryReservationService
            reservations = InventoryReservation.all_objects.filter(tenant=tenant, source_document=str(transaction_record.pk), purpose="POS_CHECKOUT", status="ALLOCATED").order_by("pk")
            for reservation in reservations:
                InventoryReservationService.release_reservation(reservation=reservation, actor=actor)
        if received <= 0:
            raise ValidationError("Cash received must be greater than zero.")
        if transaction_record.store.status != InventoryLocation.Status.ACTIVE:
            raise ValidationError("The selected retail store is inactive. Cancel this unpaid sale and choose another store.")

        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        expected_context = (
            ("register", transaction_record.register_id, authority.register.pk),
            ("register session", transaction_record.register_session_id, authority.session.pk),
            ("operator shift", transaction_record.operator_shift_id, authority.operator_shift.pk),
            ("business day", transaction_record.business_day_id, authority.business_day.pk),
        )
        if transaction_record.operator_id != actor.pk or transaction_record.device_id != device_id:
            raise ValidationError("This retail sale belongs to a different operator or device.")
        for label, actual, expected in expected_context:
            if actual != expected:
                raise ValidationError(f"This retail sale belongs to a different {label}.")

        lines = list(
            PosTransactionLine.all_objects.select_for_update()
            .select_related("sku", "sku__package_definition")
            .filter(tenant=tenant, transaction=transaction_record)
            .order_by("pk")
        )
        if not lines:
            raise ValidationError("A POS transaction needs at least one line before payment.")
        cls._recalculate(transaction_record)
        if transaction_record.total <= 0:
            raise ValidationError("Cash settlement requires a positive sale total.")
        if received < transaction_record.total:
            raise ValidationError(
                f"Cash received ({received}) is less than the sale total ({transaction_record.total})."
            )

        # If the sellable price changed after the customer-facing payment screen
        # was prepared, refresh the basket and require the cashier to reconfirm
        # the new total. No money or stock is recorded on this path.
        price_changed = False
        insufficient_stock = False
        repriced_lines = []
        for line in lines:
            item = cls._catalogue_item(
                tenant=tenant,
                branch=transaction_record.branch,
                store=transaction_record.store,
                sku=line.sku,
                quantity=line.quantity,
                customer=transaction_record.customer,
            )
            if line.sku.stock_tracking_required and item.available_quantity < line.quantity:
                insufficient_stock = True
            current_price = money(item.resolved_price.unit_price)
            if current_price != line.unit_price and _settled_intent is None:
                price_changed = True
                line.unit_price = current_price
                line.line_total = money(current_price * line.quantity)
                line.price_snapshot = cls._price_snapshot(item=item, unit_price=current_price)
                repriced_lines.append(line)
            cls._update_inventory_context(line=line, item=item, store=transaction_record.store)
        if _settled_intent and (price_changed or insufficient_stock):
            raise ValidationError("The paid basket needs stock/price review; settlement is retained and may not be repeated.")
        if price_changed or insufficient_stock:
            transaction_record.state = PosTransaction.State.DRAFT
            transaction_record.save(update_fields=["state", "updated_at"])
            for line in repriced_lines:
                line.save(update_fields=["unit_price", "line_total", "price_snapshot", "updated_at"])
            cls._recalculate(transaction_record)
            return transaction_record

        if transaction_record.currency != authority.register.currency:
            raise ValidationError("The retail transaction currency does not match the active register.")

        for line in lines:
            if line.sku.stock_tracking_required:
                cls._issue_retail_line(
                    transaction_record=transaction_record,
                    line=line,
                    actor=actor,
                )

        methods = {t.tender_type for t in ledger_tenders}
        receipt_method = (next(iter(methods)) if len(methods) == 1 else "SPLIT") if methods else "CASH"
        tender_snapshot = [{"tender_type": t.tender_type, "amount": str(t.effective_settled), "reference": t.external_reference} for t in ledger_tenders]
        receipt = RetailCashReceipt.all_objects.create(
            tenant=tenant,
            transaction=transaction_record,
            tender_type=receipt_method,
            amount=transaction_record.total,
            cash_received=sum((t.cash_received or Decimal("0") for t in ledger_tenders), Decimal("0")) if ledger_tenders else received,
            change_due=sum((t.change_due or Decimal("0") for t in ledger_tenders), Decimal("0")) if ledger_tenders else received - transaction_record.total,
            currency=transaction_record.currency,
            lines_snapshot=[
                {
                    "sku_code": line.sku.sku_code,
                    "description": line.description_snapshot,
                    "quantity": str(line.quantity),
                    "unit": line.unit,
                    "unit_price": str(line.unit_price),
                    "discount_amount": str(line.discount_amount),
                    "tax_amount": str(line.tax_amount),
                    "line_total": str(line.line_total),
                }
                for line in lines
            ],
            totals_snapshot={
                "tenders": tender_snapshot,
                "subtotal": str(transaction_record.subtotal),
                "discount_total": str(transaction_record.discount_total),
                "tax_total": str(transaction_record.tax_total),
                "total": str(transaction_record.total),
            },
            idempotency_key=key,
            created_by=actor,
        )
        transaction_record.state = PosTransaction.State.COMPLETED
        transaction_record.save(update_fields=["state", "updated_at"])

        # Keep one authoritative fiscal outbox for checkout. The former
        # taxation pipeline allocated a second invoice for this same sale.
        try:
            from apps.prescription.fiscal import FiscalService

            FiscalService.enqueue(source=transaction_record)
        except Exception:
            logger.exception(
                "Could not queue fiscalization for retail sale.",
                extra={"tenant_id": str(tenant.pk), "transaction_id": str(transaction_record.pk)},
            )

        # Queueing is deliberately best-effort: the cash receipt and inventory
        # ledger are the sale. A printer/queue fault must not collect cash twice
        # or roll back a sale that has already been settled.
        try:
            from apps.prescription.pos_printing_services import PosPrintDocumentService

            with transaction.atomic():
                PosPrintDocumentService.issue_retail_receipt(
                    transaction_record=transaction_record,
                    receipt=receipt,
                    actor=actor,
                )
        except Exception:
            logger.exception(
                "Could not queue retail receipt print job.",
                extra={"tenant_id": str(tenant.pk), "transaction_id": str(transaction_record.pk)},
            )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="PosTransaction",
            aggregate_id=str(transaction_record.pk),
            event_type="RetailCashSaleCompleted",
            payload={
                "receipt_id": str(receipt.pk),
                "receipt_number": receipt.receipt_number,
                "register_session_id": str(transaction_record.register_session_id),
                "total": str(receipt.amount),
                "currency": receipt.currency,
                "tender_type": receipt_method,
            },
        )
        return transaction_record

    @staticmethod
    def _price_snapshot(*, item: RetailCatalogueItem, unit_price: Decimal) -> dict:
        return {
            "unit_price": str(unit_price),
            "source": item.resolved_price.source,
            "source_reference": item.resolved_price.reference,
            "context_hash": item.resolved_price.context_hash,
            "considered": list(item.resolved_price.considered),
            "tax_inclusive": item.resolved_price.tax_inclusive,
        }

    @staticmethod
    def _issue_retail_line(*, transaction_record, line, actor) -> None:
        # Lock all candidate balances in stable order before selecting FEFO lots.
        # A second concurrent till must wait, then allocate against the updated
        # projection instead of issuing the same units a second time.
        balances = list(
            InventoryBalance.all_objects.select_for_update()
            .filter(
                tenant=transaction_record.tenant,
                branch=transaction_record.branch,
                location=transaction_record.store,
                sku=line.sku,
                available__gt=0,
                inventory_batch__isnull=False,
            )
            .order_by("pk")
        )
        batch_ids = sorted({balance.inventory_batch_id for balance in balances if balance.inventory_batch_id})
        list(
            InventoryBatch.all_objects.select_for_update()
            .filter(tenant=transaction_record.tenant, pk__in=batch_ids)
            .order_by("pk")
        )
        allocations = FEFOAllocationService.allocate_stock(
            tenant=transaction_record.tenant,
            branch=transaction_record.branch,
            location=transaction_record.store,
            sku=line.sku,
            required_quantity=line.quantity,
            minimum_expiry_date=timezone.localdate() + timedelta(days=1),
        )
        for batch, quantity in allocations:
            InventoryLedgerService.post_entry(
                tenant=transaction_record.tenant,
                branch=transaction_record.branch,
                location=transaction_record.store,
                sku=line.sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.ISSUE,
                quantity_delta=-quantity,
                unit=line.unit,
                base_quantity_delta=-quantity,
                effective_timestamp=timezone.now(),
                source_document_type="POS_RETAIL_TRANSACTION",
                source_document_id=str(transaction_record.pk),
                source_line_id=str(line.pk),
                idempotency_key=f"pos-retail-issue-{transaction_record.pk}-{line.pk}-{batch.pk}",
                actor=actor,
                reason_code="RETAIL_CASH_SALE",
                notes=f"Cash sale {transaction_record.transaction_number}",
            )

    @classmethod
    def _editable_transaction(cls, *, tenant, transaction_id, actor, device_id):
        transaction_record = PosTransaction.all_objects.select_for_update().select_related("branch").filter(
            tenant=tenant, pk=transaction_id
        ).first()
        if transaction_record is None:
            raise ValidationError("POS transaction not found.")
        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        cls._validate_editable_transaction(transaction_record, authority)
        return transaction_record, authority

    @classmethod
    def _cancelable_transaction(cls, *, tenant, transaction_id, actor, device_id):
        transaction_record = PosTransaction.all_objects.select_for_update().select_related("branch").filter(
            tenant=tenant, pk=transaction_id
        ).first()
        if transaction_record is None:
            raise ValidationError("POS transaction not found.")
        if transaction_record.state not in {
            PosTransaction.State.DRAFT,
            PosTransaction.State.HELD,
            PosTransaction.State.READY_FOR_PAYMENT,
        }:
            raise ValidationError("Only an unpaid POS transaction can be cancelled.")
        authority = cls._authority(
            tenant=tenant,
            branch=transaction_record.branch,
            actor=actor,
            device_id=device_id,
        )
        cls._validate_transaction_context(
            transaction_record,
            authority,
            actor=actor,
            device_id=device_id,
        )
        return transaction_record, authority

    @staticmethod
    def _validate_editable_transaction(transaction_record, authority) -> None:
        if transaction_record.state not in {PosTransaction.State.DRAFT, PosTransaction.State.HELD}:
            raise ValidationError("This POS transaction is no longer editable.")
        PosRetailService._validate_transaction_context(
            transaction_record,
            authority,
            actor=authority.operator_shift.operator,
            device_id=authority.register.device_id,
        )

    @staticmethod
    def _validate_transaction_context(transaction_record, authority, *, actor, device_id) -> None:
        context = (
            ("register", transaction_record.register_id, authority.register.pk),
            ("register session", transaction_record.register_session_id, authority.session.pk),
            ("operator shift", transaction_record.operator_shift_id, authority.operator_shift.pk),
            ("business day", transaction_record.business_day_id, authority.business_day.pk),
            ("operator", transaction_record.operator_id, actor.pk),
            ("device", transaction_record.device_id, device_id),
        )
        for label, actual, expected in context:
            if actual != expected:
                raise ValidationError(f"This POS transaction belongs to a different {label}.")

    @staticmethod
    def _require_stock(*, item: RetailCatalogueItem, sku, quantity) -> None:
        if not sku.stock_tracking_required:
            return
        if item.available_quantity < Decimal(str(quantity)):
            raise ValidationError(
                f"Insufficient eligible stock for {sku.display_name}. Available: {item.available_quantity}."
            )

    @staticmethod
    def _update_inventory_context(*, line, item: RetailCatalogueItem, store):
        PosTransactionInventoryContext.all_objects.update_or_create(
            tenant=line.tenant,
            transaction_line=line,
            defaults={
                "store": store,
                "available_quantity": item.available_quantity,
                "stock_state": item.stock_state,
                "policy": {"stock_tracking_required": line.sku.stock_tracking_required},
            },
        )

    @staticmethod
    def _recalculate(transaction_record) -> None:
        totals = PosTransactionLine.all_objects.filter(
            tenant_id=transaction_record.tenant_id,
            transaction=transaction_record,
        ).aggregate(
            subtotal=Sum("line_total"),
            discount_total=Sum("discount_amount"),
            tax_total=Sum("tax_amount"),
        )
        transaction_record.subtotal = money(totals["subtotal"] or Decimal("0.00"))
        transaction_record.discount_total = money(totals["discount_total"] or Decimal("0.00"))
        transaction_record.tax_total = money(totals["tax_total"] or Decimal("0.00"))
        transaction_record.total = money(
            transaction_record.subtotal - transaction_record.discount_total + transaction_record.tax_total
        )
        transaction_record.save(update_fields=[
            "subtotal", "discount_total", "tax_total", "total", "updated_at",
        ])
