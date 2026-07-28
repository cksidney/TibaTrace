from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventory.models import BarcodeMaster, InventoryBalance, InventoryBatch, InventoryLocation
from apps.medicines.models import BranchAssortment, CommercialSKU, ProductIdentifier
from apps.pos_shift.authority import RegisterAuthority, RegisterAuthorityService
from apps.pricing.catalogue import PriceCatalogue
from apps.pricing.resolution import PricingContext, PricingError, money

from .models import PosTransaction, PosTransactionInventoryContext, PosTransactionLine


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
                available__gt=0,
                expiry_status="NORMAL",
            )
            .filter(
                Q(inventory_batch__isnull=True)
                | Q(
                    inventory_batch__quality_status=InventoryBatch.QualityStatus.RELEASED,
                    inventory_batch__recall_status=InventoryBatch.RecallStatus.NONE,
                )
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
    def create_draft(*, tenant, branch, store_id, actor, device_id: str, customer=None, patient=None):
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
    def search_catalogue(*, tenant, branch, store_id, actor, device_id: str, query: str, customer=None):
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
    def resolve_barcode(*, tenant, barcode: str) -> CommercialSKU:
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
    def add_line(*, tenant, transaction_id, actor, device_id: str, sku_id, quantity, scan_source="SEARCH"):
        transaction_record = (
            PosTransaction.all_objects.select_for_update()
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
    def set_quantity(*, tenant, transaction_id, line_id, actor, device_id: str, quantity):
        transaction_record = PosTransaction.all_objects.select_for_update().select_related(
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
    def remove_line(*, tenant, transaction_id, line_id, actor, device_id: str):
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
    def hold(*, tenant, transaction_id, actor, device_id: str, reason: str = ""):
        _require(actor, tenant.pk, "pos.transaction.hold")
        transaction_record, authority = cls._editable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        if not transaction_record.lines.exists():
            raise ValidationError("An empty POS transaction cannot be held.")
        transaction_record.state = PosTransaction.State.HELD
        transaction_record.hold_reason = reason.strip()
        transaction_record.held_at = timezone.now()
        transaction_record.save(update_fields=["state", "hold_reason", "held_at", "updated_at"])
        return transaction_record

    @classmethod
    @transaction.atomic
    def resume(*, tenant, transaction_id, actor, device_id: str):
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
    def cancel(*, tenant, transaction_id, actor, device_id: str, reason: str):
        _require(actor, tenant.pk, "pos.transaction.cancel")
        transaction_record, authority = cls._editable_transaction(
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
    def ready_for_payment(*, tenant, transaction_id, actor, device_id: str):
        _require(actor, tenant.pk, "pos.payment.accept")
        transaction_record, authority = cls._editable_transaction(
            tenant=tenant, transaction_id=transaction_id, actor=actor, device_id=device_id
        )
        lines = list(transaction_record.lines.select_related("sku"))
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
        transaction_record.state = PosTransaction.State.READY_FOR_PAYMENT
        transaction_record.save(update_fields=["state", "updated_at"])
        return transaction_record

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

    @staticmethod
    def _validate_editable_transaction(transaction_record, authority) -> None:
        if transaction_record.state not in {PosTransaction.State.DRAFT, PosTransaction.State.HELD}:
            raise ValidationError("This POS transaction is no longer editable.")
        context = (
            ("register", transaction_record.register_id, authority.register.pk),
            ("register session", transaction_record.register_session_id, authority.session.pk),
            ("operator shift", transaction_record.operator_shift_id, authority.operator_shift.pk),
            ("business day", transaction_record.business_day_id, authority.business_day.pk),
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
        totals = transaction_record.lines.aggregate(
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
