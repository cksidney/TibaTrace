"""Warehouse coordination tied to authoritative custody documents.

Task transitions never post stock. Completion verifies the source workflow has
actually completed; assigning or cancelling a task cannot replace that workflow.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.models import InventoryLedgerEntry, StocktakeSession, StockTransfer, WarehouseTask
from apps.inventory.services import StockTransferService
from apps.procurement.models import GoodsReceipt, QualityDecision, ReceivedBatch
from apps.sales.models import DispatchOrder, PackingSession, PickingTask

SOURCES = {
    "RECEIVE": (GoodsReceipt, "receiving_branch_id"),
    "INSPECT": (ReceivedBatch, "grn_line.goods_receipt.receiving_branch_id"),
    "PUTAWAY": (ReceivedBatch, "grn_line.goods_receipt.receiving_branch_id"),
    "PICK": (PickingTask, "sales_order.branch_id"),
    "PACK": (PackingSession, "branch_id"),
    "DISPATCH": (DispatchOrder, "branch_id"),
    "TRANSFER_RECEIVE": (StockTransfer, "destination_branch_id"),
    "REPLENISH": (StockTransfer, "destination_branch_id"),
    "COUNT": (StocktakeSession, "branch_id"),
}


def source(tenant_id, task_type, source_id):
    if task_type not in SOURCES:
        raise ValidationError("Select a supported warehouse operation.")
    model, branch_path = SOURCES[task_type]
    obj = model.all_objects.filter(tenant_id=tenant_id, pk=source_id).first()
    if obj is None:
        raise ValidationError("Select an existing source document in this tenant.")
    branch_id = obj
    for segment in branch_path.split("."):
        branch_id = getattr(branch_id, segment)
    return obj, branch_id


def audit(item, actor, action):
    log_audit(
        tenant_id=item.tenant_id,
        actor_id=getattr(actor, "pk", None),
        action="WAREHOUSE_TASK_" + action,
        model_name="WarehouseTask",
        object_id=item.pk,
        metadata={
            "source_type": item.source_type,
            "source_id": str(item.source_id),
            "status": item.status,
            "evidence": item.evidence,
        },
    )


@transaction.atomic
def create(*, tenant, actor, task_type, source_id, priority=1):
    if actor:
        StockTransferService._require_authority(tenant.pk, actor)
    obj, branch_id = source(tenant.pk, task_type, source_id)
    type(tenant).objects.select_for_update().get(pk=tenant.pk)
    item, created = WarehouseTask.all_objects.get_or_create(
        tenant=tenant,
        task_type=task_type,
        source_type=type(obj).__name__,
        source_id=obj.pk,
        defaults={"branch_id": branch_id, "priority": priority},
    )
    if created:
        audit(item, actor, "CREATED")
    return item


def completed(item, obj):
    kind = item.task_type
    if kind == "RECEIVE":
        batches = ReceivedBatch.all_objects.filter(tenant_id=item.tenant_id, grn_line__goods_receipt=obj)
        return batches.exists() and all(
            InventoryLedgerEntry.all_objects.filter(
                tenant_id=item.tenant_id,
                source_document_type__in=["RECEIVED_BATCH_QUARANTINE", "RECEIVED_BATCH"],
                source_document_id=str(batch.pk),
                entry_type="RECEIPT",
            ).exists()
            for batch in batches
        )
    if kind == "INSPECT":
        return QualityDecision.all_objects.filter(
            tenant_id=item.tenant_id, batch=obj, inspector__isnull=False, decision_by__isnull=False
        ).exists()
    if kind == "PUTAWAY":
        posted = InventoryLedgerEntry.all_objects.filter(
            tenant_id=item.tenant_id,
            source_document_id=str(obj.pk),
            source_document_type__in=["RECEIVED_BATCH", "RECEIVED_BATCH_RELEASE"],
            entry_type__in=["RECEIPT", "TRANSFER_IN"],
        )
        return (
            obj.quality_status == "RELEASED"
            and sum(entry.base_quantity_delta for entry in posted) == obj.accepted_quantity
            and obj.accepted_quantity > 0
        )
    return (
        obj.status
        in {
            "PICK": {"VERIFIED"},
            "PACK": {"CLOSED"},
            "DISPATCH": {"DISPATCHED", "IN_TRANSIT", "PARTIALLY_DELIVERED", "DELIVERED", "CLOSED"},
            "TRANSFER_RECEIVE": {"RECEIVED", "CLOSED"},
            "REPLENISH": {"RECEIVED", "CLOSED"},
            "COUNT": {"POSTED", "CLOSED"},
        }[kind]
    )


@transaction.atomic
def transition(*, item, actor, action, evidence="", assignee=None):
    StockTransferService._require_authority(item.tenant_id, actor)
    item = WarehouseTask.all_objects.select_for_update().get(pk=item.pk, tenant_id=item.tenant_id)
    if action not in {"assign", "start", "complete", "cancel", "reopen"}:
        raise ValidationError("Unknown warehouse transition.")
    if item.status == "CANCELLED" and action == "reopen":
        if not str(evidence).strip():
            raise ValidationError("Record why this warehouse task should reopen.")
        item.status, item.assigned_user, item.evidence = "PENDING", None, evidence
        item.save()
        audit(item, actor, "REOPENED")
        return item
    if item.status in {"COMPLETED", "CANCELLED"}:
        if (item.status == "COMPLETED" and action == "complete") or (item.status == "CANCELLED" and action == "cancel"):
            return item
        raise ValidationError("Terminal warehouse tasks cannot change.")
    if action == "assign":
        if (
            item.status not in {"PENDING", "ASSIGNED"}
            or assignee is None
            or not assignee.is_active
            or assignee.tenant_id != item.tenant_id
            or not assignee.has_capability("inventory.manage", tenant_id=item.tenant_id)
        ):
            raise ValidationError("Assign a pending task to an active warehouse operator in this tenant.")
        item.assigned_user, item.status = assignee, "ASSIGNED"
    elif action == "start":
        if item.status != "ASSIGNED" or item.assigned_user_id != actor.pk:
            raise ValidationError("Only the assigned operator can start an assigned task.")
        item.status = "IN_PROGRESS"
    elif action == "complete":
        if item.status != "IN_PROGRESS" or item.assigned_user_id != actor.pk or not str(evidence).strip():
            raise ValidationError("The assigned operator must start the task and record completion evidence.")
        obj, branch_id = source(item.tenant_id, item.task_type, item.source_id)
        if branch_id != item.branch_id or not completed(item, obj):
            raise ValidationError("Complete the authoritative source workflow before closing this task.")
        item.status, item.completed_by, item.completed_at, item.evidence = "COMPLETED", actor, timezone.now(), evidence
    else:
        if not str(evidence).strip():
            raise ValidationError("Task cancellation requires a reason. Source documents remain actionable.")
        item.status, item.evidence = "CANCELLED", evidence
    item.save()
    audit(item, actor, action.upper())
    return item
