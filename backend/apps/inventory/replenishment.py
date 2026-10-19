"""Configured branch min/max planning; recommendations become governed demand."""

from decimal import ROUND_CEILING, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.models import InventoryBalance, ReplenishmentPolicy, ReplenishmentRecommendation, StockTransferLine
from apps.inventory.operations import number
from apps.inventory.services import StockTransferService
from apps.procurement.models import PurchaseOrderLine, PurchaseRequisitionLine
from apps.procurement.services.procurement_service import ProcurementService


def audit(item, actor, action, **metadata):
    log_audit(
        tenant_id=item.tenant_id,
        actor_id=getattr(actor, "pk", None),
        action="REPLENISHMENT_" + action,
        model_name=type(item).__name__,
        object_id=item.pk,
        metadata=metadata,
    )


@transaction.atomic
def configure(
    *,
    tenant,
    actor,
    branch,
    sku,
    destination,
    safety_stock,
    reorder_point,
    target_stock,
    order_multiple=1,
    lead_days=1,
    enabled=True,
):
    StockTransferService._require_authority(tenant.pk, actor)
    safety, point, target = [number(value) for value in (safety_stock, reorder_point, target_stock)]
    if not 0 <= safety <= point < target or not 1 <= order_multiple <= 1000000 or not 0 <= lead_days <= 3650:
        raise ValidationError(
            "Require 0 ≤ safety stock ≤ reorder point < target, a positive order multiple and valid lead days."
        )
    if (
        sku.tenant_id != tenant.pk
        or branch.tenant_id != tenant.pk
        or destination.tenant_id != tenant.pk
        or destination.branch_id != branch.pk
        or destination.status != "ACTIVE"
        or any(
            (
                destination.quarantine_capability,
                destination.damaged_goods_capability,
                destination.expiry_hold_capability,
                destination.returns_capability,
            )
        )
        or not sku.stock_tracking_required
        or sku.status != "ACTIVE"
    ):
        raise ValidationError("Choose an active stock SKU and saleable destination in the same tenant and branch.")
    type(tenant).objects.select_for_update().get(pk=tenant.pk)
    item, _ = ReplenishmentPolicy.all_objects.update_or_create(
        tenant=tenant,
        branch=branch,
        sku=sku,
        defaults=dict(
            destination=destination,
            safety_stock=safety,
            reorder_point=point,
            target_stock=target,
            order_multiple=order_multiple,
            lead_days=lead_days,
            enabled=enabled,
            configured_by=actor,
        ),
    )
    audit(item, actor, "POLICY_CONFIGURED", safety=str(safety), reorder=str(point), target=str(target), enabled=enabled)
    return item


def position(policy):
    balances = InventoryBalance.all_objects.filter(
        tenant_id=policy.tenant_id,
        branch=policy.branch,
        sku=policy.sku,
        location__status="ACTIVE",
        location__quarantine_capability=False,
        location__damaged_goods_capability=False,
        location__expiry_hold_capability=False,
        location__returns_capability=False,
        inventory_batch__quality_status="RELEASED",
        inventory_batch__recall_status="NONE",
    )
    from django.db.models import Q

    balances = balances.filter(
        Q(inventory_batch__expiry_date__gt=timezone.localdate())
        | Q(sku__expiry_tracking_required=False, inventory_batch__expiry_date__isnull=True)
    )
    available = balances.aggregate(total=Sum("available"))["total"] or Decimal(0)
    orders = PurchaseOrderLine.all_objects.filter(
        tenant_id=policy.tenant_id,
        purchase_order__ordering_branch=policy.branch,
        sku=policy.sku,
        purchase_order__status__in=["DRAFT", "SUBMITTED", "APPROVED", "SENT", "ACKNOWLEDGED", "PARTIALLY_RECEIVED"],
    )
    ordered = sum((max(0, row.ordered_quantity - row.received_quantity) for row in orders), Decimal(0))
    demand = PurchaseRequisitionLine.all_objects.filter(
        tenant_id=policy.tenant_id,
        requisition__requesting_branch=policy.branch,
        sku=policy.sku,
        requisition__status__in=["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_ORDERED"],
    ).exclude(status="REJECTED")
    requested = demand.aggregate(total=Sum("outstanding_quantity"))["total"] or Decimal(0)
    transfers = StockTransferLine.all_objects.filter(
        tenant_id=policy.tenant_id,
        transfer__destination_branch=policy.branch,
        sku=policy.sku,
        transfer__status__in=["SUBMITTED", "APPROVED", "DISPATCHED", "IN_TRANSIT", "PARTIALLY_RECEIVED"],
    )
    incoming = sum(
        (
            max(
                0,
                (
                    row.dispatched_quantity
                    if row.transfer.status in {"DISPATCHED", "IN_TRANSIT", "PARTIALLY_RECEIVED"}
                    else row.requested_quantity
                )
                - row.received_quantity
                - row.damaged_quantity
                - row.lost_quantity,
            )
            for row in transfers
        ),
        Decimal(0),
    )
    # Received quantities still in quality custody must not trigger duplicate buying.
    from apps.procurement.models import ReceivedBatch

    held_batches = ReceivedBatch.all_objects.filter(
        tenant_id=policy.tenant_id,
        grn_line__goods_receipt__receiving_branch=policy.branch,
        sku=policy.sku,
        quality_status__in=["PENDING_INSPECTION", "QUARANTINED", "PARTIALLY_RELEASED"],
    )
    from apps.procurement.models import SupplierReturnLine

    returned_hold = dict(
        SupplierReturnLine.all_objects.filter(
            tenant_id=policy.tenant_id,
            supplier_return__goods_receipt__receiving_branch=policy.branch,
            sku=policy.sku,
            supplier_return__return_category="QUALITY_REJECTION",
            batch__quality_status__in=["PENDING_INSPECTION", "QUARANTINED", "PARTIALLY_RELEASED"],
        )
        .exclude(supplier_return__status="REJECTED")
        .values("batch_id")
        .annotate(total=Sum("quantity"))
        .values_list("batch_id", "total")
    )
    # Rejected units and return claims can describe the same units. Calculate
    # each batch's usable remainder once, without consuming another lot's hold.
    held = sum(
        (
            max(
                0,
                batch.received_quantity
                - batch.accepted_quantity
                - max(batch.rejected_quantity, returned_hold.get(batch.pk, 0)),
            )
            for batch in held_batches
        ),
        Decimal(0),
    )
    effective = available + ordered + requested + incoming + held
    quantity = Decimal(0)
    if effective <= policy.reorder_point:
        quantity = ((policy.target_stock - effective) / policy.order_multiple).to_integral_value(
            rounding=ROUND_CEILING
        ) * policy.order_multiple
    return quantity, {
        key: str(value)
        for key, value in dict(
            available=available,
            pending_orders=ordered,
            pending_requisitions=requested,
            inbound_transfers=incoming,
            quality_hold=held,
            inventory_position=effective,
            safety_stock=policy.safety_stock,
            reorder_point=policy.reorder_point,
            target_stock=policy.target_stock,
        ).items()
    }


@transaction.atomic
def refresh(tenant):
    # Serializes first creation and conversion with manual policy updates.
    type(tenant).objects.select_for_update().get(pk=tenant.pk)
    count = 0
    for policy in (
        ReplenishmentPolicy.all_objects.select_for_update()
        .filter(tenant=tenant)
        .select_related("sku", "branch", "destination")
    ):
        pending = (
            ReplenishmentRecommendation.all_objects.select_for_update()
            .filter(tenant=tenant, policy=policy, status="PENDING")
            .first()
        )
        quantity, snapshot = position(policy) if policy.enabled else (0, {})
        if policy.destination.status != "ACTIVE" or policy.sku.status != "ACTIVE":
            quantity = 0
        if not quantity:
            if pending:
                pending.status = "WITHDRAWN"
                pending.save(update_fields=["status", "updated_at"])
                audit(pending, None, "WITHDRAWN", snapshot=snapshot)
            continue
        if pending is None:
            prior_rejection = (
                ReplenishmentRecommendation.all_objects.filter(tenant=tenant, policy=policy, status="REJECTED")
                .order_by("-updated_at")
                .first()
            )
            if prior_rejection and prior_rejection.snapshot == snapshot:
                continue
            pending = ReplenishmentRecommendation.all_objects.create(
                tenant=tenant, branch=policy.branch, sku=policy.sku, policy=policy, recommended_quantity=quantity
            )
        pending.recommended_quantity, pending.snapshot = quantity, snapshot
        pending.save(update_fields=["recommended_quantity", "snapshot", "updated_at"])
        count += 1
    return count


@transaction.atomic
def decide(*, item, actor, approve, reason):
    StockTransferService._require_authority(item.tenant_id, actor)
    type(item.tenant).objects.select_for_update().get(pk=item.tenant_id)
    item = (
        ReplenishmentRecommendation.all_objects.select_for_update(of=("self",))
        .select_related("policy__sku__package_definition", "policy__branch")
        .get(pk=item.pk, tenant_id=item.tenant_id)
    )
    if not str(reason).strip():
        raise ValidationError("Record the demand review reason.")
    if item.status != "PENDING":
        if (
            item.decided_by_id == actor.pk
            and item.status == ("SUBMITTED" if approve else "REJECTED")
            and item.reason == reason
        ):
            return item
        raise ValidationError("This recommendation is no longer pending.")
    if not item.policy or not item.policy.enabled:
        raise ValidationError("The replenishment policy is disabled or missing.")
    if approve:
        if not actor.has_capability("procurement.write", tenant_id=item.tenant_id):
            raise ValidationError("Creating procurement demand requires procurement.write authority.")
        quantity, snapshot = position(item.policy)
        if quantity != item.recommended_quantity or snapshot != item.snapshot:
            raise ValidationError("Stock or pending demand changed; refresh and review the current recommendation.")
        requisition = ProcurementService.create_requisition(
            tenant=item.tenant,
            requesting_branch=item.branch,
            requester=actor,
            requested_delivery_date=timezone.localdate() + timezone.timedelta(days=item.policy.lead_days),
            lines_data=[
                dict(
                    sku=item.sku,
                    requested_quantity=int(quantity),
                    purchase_unit=item.sku.package_definition.unit_of_measure,
                )
            ],
            justification=reason,
            requisition_number=f"REPL-{item.pk.hex[:16]}",
        )
        ProcurementService.submit_requisition(requisition=requisition)
        item.requisition = requisition
    item.status, item.decided_by, item.reason = ("SUBMITTED" if approve else "REJECTED"), actor, reason
    item.save(update_fields=["status", "decided_by", "reason", "requisition", "updated_at"])
    audit(item, actor, item.status, reason=reason, quantity=str(item.recommended_quantity))
    return item
