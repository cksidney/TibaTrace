"""Receipt-linked physical supplier returns and independently reconciled credit."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.models import InventoryBalance, InventoryBatch
from apps.inventory.services import InventoryLedgerService, StockTransferService
from apps.procurement.models import GoodsReceiptLine, ReceivedBatch, Supplier, SupplierReturn, SupplierReturnLine


def authority(item, actor, capability="procurement.write"):
    if (
        not actor
        or not actor.is_active
        or not any(actor.has_capability(cap, tenant_id=item.tenant_id) for cap in (capability,))
    ):
        raise ValidationError("Supplier returns require procurement management authority in this tenant.")


def audit(item, actor, action):
    log_audit(
        tenant_id=item.tenant_id,
        actor_id=actor.pk,
        action="SUPPLIER_RETURN_" + action,
        model_name="SupplierReturn",
        object_id=item.pk,
        metadata={
            "status": item.status,
            "expected_credit": str(item.expected_credit),
            "credit_amount": str(item.credit_amount),
            "credit_reference": item.credit_reference,
        },
    )


class SupplierReturnService:
    @staticmethod
    @transaction.atomic
    def request_return(*, tenant, return_number, goods_receipt, reason, requested_by=None, expected_credit=None, return_category="QUALITY_REJECTION"):
        if goods_receipt.tenant_id != tenant.pk or not str(reason or "").strip():
            raise ValidationError("Select a tenant receipt and provide a return reason.")
        if return_category not in {"QUALITY_REJECTION", "RECALL", "COMMERCIAL"}:
            raise ValidationError("Choose an explicit supplier return category.")
        if requested_by:
            authority(goods_receipt, requested_by)
        type(tenant).objects.select_for_update().get(pk=tenant.pk)
        existing = SupplierReturn.all_objects.filter(tenant=tenant, return_number=return_number).first()
        if existing:
            if existing.goods_receipt_id != goods_receipt.pk or existing.reason != reason or existing.return_category != return_category:
                raise ValidationError("Return number already belongs to a different request.")
            return existing
        if expected_credit is not None and (
            not Decimal(str(expected_credit)).is_finite() or Decimal(str(expected_credit)) < 0
        ):
            raise ValidationError("Expected credit must be nonnegative.")
        return SupplierReturn.all_objects.create(
            tenant=tenant,
            return_number=return_number,
            goods_receipt=goods_receipt,
            supplier=goods_receipt.supplier,
            reason=reason,
            requested_by=requested_by,
            expected_credit=expected_credit,
            return_category=return_category,
            status="REQUESTED",
        )

    @staticmethod
    @transaction.atomic
    def add_return_line(*, supplier_return, sku, quantity, batch=None, source_location=None):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        if item.status != "REQUESTED":
            raise ValidationError("Lines can only be added while the return is still requested.")
        if sku.tenant_id != item.tenant_id or not quantity or quantity <= 0:
            raise ValidationError("Add a positive tenant SKU quantity to a requested return.")
        eligible = GoodsReceiptLine.all_objects.filter(
            tenant_id=item.tenant_id, goods_receipt=item.goods_receipt, sku=sku
        ).aggregate(delivered=Sum("delivered_quantity"), rejected=Sum("rejected_quantity"), quarantined=Sum("quarantined_quantity"))
        allowance = ((eligible["rejected"] or 0) + (eligible["quarantined"] or 0)) if item.return_category == "QUALITY_REJECTION" else (eligible["delivered"] or 0)
        if allowance == 0:
            raise ValidationError("This receipt has nothing to return for the selected category; select an explicit recall or commercial agreement for accepted stock.")
        claimed = (
            SupplierReturnLine.all_objects.filter(
                tenant_id=item.tenant_id, supplier_return__goods_receipt=item.goods_receipt, sku=sku
            )
            .exclude(supplier_return__status="REJECTED")
            .aggregate(total=Sum("quantity"))["total"]
            or 0
        )
        if quantity + claimed > allowance:
            raise ValidationError(f"Only {max(0, allowance - claimed)} remains eligible; the remaining receipt allowance is shared across all returns.")
        inventory_batch = None
        if batch is not None:
            batch = ReceivedBatch.all_objects.select_for_update().get(pk=batch.pk, tenant_id=item.tenant_id)
            if (
                batch.tenant_id != item.tenant_id
                or batch.sku_id != sku.pk
                or batch.grn_line.goods_receipt_id != item.goods_receipt_id
            ):
                raise ValidationError("The returned batch must belong to this receipt and SKU.")
            batch_claims = SupplierReturnLine.all_objects.filter(tenant_id=item.tenant_id, batch=batch).exclude(supplier_return__status="REJECTED").aggregate(total=Sum("quantity"))["total"] or 0
            batch_allowance = batch.received_quantity - batch.accepted_quantity if item.return_category == "QUALITY_REJECTION" else batch.received_quantity
            if batch_claims + quantity > batch_allowance:
                raise ValidationError("This batch is already allocated to other supplier returns.")
            inventory_batch = InventoryBatch.all_objects.filter(
                tenant_id=item.tenant_id, sku=sku, manufacturer_batch_number=batch.manufacturer_batch_number
            ).first()
            if inventory_batch is None:
                raise ValidationError("Receive this batch into tracked quarantine custody before returning it.")
        if source_location is not None and (
            source_location.tenant_id != item.tenant_id
            or source_location.branch_id != item.goods_receipt.receiving_branch_id
        ):
            raise ValidationError("Select custody in the receiving branch.")
        return SupplierReturnLine.all_objects.create(
            tenant_id=item.tenant_id,
            supplier_return=item,
            sku=sku,
            quantity=quantity,
            batch=batch,
            inventory_batch=inventory_batch,
            source_location=source_location,
        )

    @staticmethod
    def add_line(*, supplier_return, sku, quantity, reason="", batch=None, source_location=None):
        return SupplierReturnService.add_return_line(
            supplier_return=supplier_return, sku=sku, quantity=quantity, batch=batch, source_location=source_location
        )

    @staticmethod
    @transaction.atomic
    def approve(*, supplier_return, approver):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        authority(item, approver, "procurement.approve")
        if item.status != "REQUESTED" or not item.requested_by_id or item.requested_by_id == approver.pk:
            raise ValidationError("A requested return requires an approver independent of its named requester.")
        lines = SupplierReturnLine.all_objects.filter(tenant_id=item.tenant_id, supplier_return=item)
        if (
            item.expected_credit is None
            or not lines.exists()
            or lines.filter(inventory_batch__isnull=True).exists()
            or lines.filter(source_location__isnull=True).exists()
        ):
            raise ValidationError(
                "Confirm the expected supplier credit and exact physical batch/custody for every line before approval."
            )
        item.approved_by = approver
        item.status = "APPROVED"
        item.save(update_fields=["approved_by", "status", "updated_at"])
        audit(item, approver, "APPROVED")
        return item

    @staticmethod
    @transaction.atomic
    def dispatch(*, supplier_return, actor=None):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        authority(item, actor)
        StockTransferService._require_authority(item.tenant_id, actor)
        if item.status in {"DISPATCHED", "CREDIT_PENDING", "CLOSED"}:
            return item
        if item.status != "APPROVED":
            raise ValidationError("Only an approved return can be dispatched.")
        for line in SupplierReturnLine.all_objects.filter(tenant_id=item.tenant_id, supplier_return=item).select_related("inventory_batch", "source_location", "sku__package_definition"):
            if line.batch_id:
                ReceivedBatch.all_objects.select_for_update().get(pk=line.batch_id, tenant_id=item.tenant_id)
            location, batch = line.source_location, line.inventory_batch
            if not location or not batch or location.status != "ACTIVE":
                raise ValidationError("Every return line needs an active custody location and tracked batch.")
            balances = list(
                InventoryBalance.all_objects.select_for_update().filter(
                    tenant_id=item.tenant_id, sku=line.sku, location=location, inventory_batch=batch
                )
            )
            if sum((b.on_hand - b.reserved for b in balances), Decimal(0)) < line.quantity:
                raise ValidationError("Insufficient unreserved physical custody to dispatch this supplier return.")
            InventoryLedgerService.post_entry(
                tenant=item.tenant,
                branch=location.branch,
                location=location,
                sku=line.sku,
                inventory_batch=batch,
                entry_type="RETURN_OUT",
                quantity_delta=-Decimal(line.quantity),
                base_quantity_delta=-Decimal(line.quantity),
                unit=line.sku.package_definition.unit_of_measure,
                effective_timestamp=timezone.now(),
                source_document_type="SUPPLIER_RETURN",
                source_document_id=str(item.pk),
                source_line_id=str(line.pk),
                idempotency_key=f"supplier-return:{item.pk}:{line.pk}",
                actor=actor,
                reason_code="SUPPLIER_RETURN",
                notes=item.reason,
            )
        item.status = "DISPATCHED"
        item.dispatched_by = actor
        item.save(update_fields=["status", "dispatched_by", "updated_at"])
        for received in ReceivedBatch.all_objects.select_for_update().filter(tenant_id=item.tenant_id, pk__in=SupplierReturnLine.all_objects.filter(tenant_id=item.tenant_id, supplier_return=item).values("batch_id")).order_by("pk"):
            if item.return_category != "QUALITY_REJECTION":
                continue
            returned = SupplierReturnLine.all_objects.filter(tenant_id=item.tenant_id, batch=received, supplier_return__return_category="QUALITY_REJECTION", supplier_return__status__in=["DISPATCHED", "CREDIT_PENDING", "CLOSED"]).aggregate(total=Sum("quantity"))["total"] or 0
            previous_held = received.quarantined_quantity
            received.quarantined_quantity = max(0, received.received_quantity - received.accepted_quantity - max(received.rejected_quantity, returned))
            if received.accepted_quantity and not received.quarantined_quantity:
                received.quality_status = "RELEASED"
            received.save(update_fields=["quarantined_quantity", "quality_status", "updated_at"])
            receipt_line = GoodsReceiptLine.all_objects.select_for_update().get(pk=received.grn_line_id, tenant_id=item.tenant_id)
            receipt_line.quarantined_quantity = max(0, receipt_line.quarantined_quantity - previous_held + received.quarantined_quantity)
            receipt_line.save(update_fields=["quarantined_quantity", "updated_at"])
        audit(item, actor, "DISPATCHED")
        return item

    @staticmethod
    @transaction.atomic
    def record_credit(*, supplier_return, actor, amount, reference, variance_reason=""):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        authority(item, actor)
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount < 0 or not str(reference).strip():
            raise ValidationError("A nonnegative credit amount and supplier credit-note reference are required.")
        if item.status == "CREDIT_PENDING" and item.credit_amount == amount and item.credit_reference == reference:
            return item
        if item.status != "DISPATCHED":
            raise ValidationError("Record supplier credit only after physical dispatch.")
        if amount != item.expected_credit and not str(variance_reason).strip():
            raise ValidationError("Explain the difference between expected and actual supplier credit.")
        Supplier.all_objects.select_for_update().get(pk=item.supplier_id, tenant_id=item.tenant_id)
        if (
            SupplierReturn.all_objects.filter(
                tenant_id=item.tenant_id, supplier=item.supplier, credit_reference=reference
            )
            .exclude(pk=item.pk)
            .exists()
        ):
            raise ValidationError("This supplier credit reference is already allocated to another return.")
        item.credit_amount, item.credit_reference, item.credit_variance_reason = amount, reference, variance_reason
        item.credit_recorded_by, item.status = actor, "CREDIT_PENDING"
        item.save(
            update_fields=[
                "credit_amount",
                "credit_reference",
                "credit_variance_reason",
                "credit_recorded_by",
                "status",
                "updated_at",
            ]
        )
        audit(item, actor, "CREDIT_RECORDED")
        return item

    @staticmethod
    @transaction.atomic
    def close_credit(*, supplier_return, actor):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        authority(item, actor, "procurement.approve")
        if actor.pk == item.credit_recorded_by_id:
            raise ValidationError("A separate authorized person must reconcile the supplier credit.")
        if item.status == "CLOSED":
            return item
        if item.status != "CREDIT_PENDING":
            raise ValidationError("Record a supplier credit note before reconciliation.")
        item.status, item.credit_closed_by = "CLOSED", actor
        item.save(update_fields=["status", "credit_closed_by", "updated_at"])
        audit(item, actor, "CLOSED")
        return item

    @staticmethod
    @transaction.atomic
    def reject(*, supplier_return, actor, reason):
        item = SupplierReturn.all_objects.select_for_update().get(pk=supplier_return.pk)
        authority(item, actor, 'procurement.approve')
        if item.status != 'REQUESTED' or item.requested_by_id == actor.pk or not str(reason).strip():
            raise ValidationError('A separate approver can reject a requested return with a reason; dispatched stock cannot be cancelled.')
        item.status = 'REJECTED'
        item.save(update_fields=['status', 'updated_at'])
        log_audit(tenant_id=item.tenant_id, actor_id=actor.pk, action='SUPPLIER_RETURN_REJECTED', model_name='SupplierReturn', object_id=item.pk, metadata={'reason': reason, 'prior_requester': str(item.requested_by_id)})
        return item
