"""Report-specific, tenant-bound facts. Planned packs never become fake snapshots."""
from dataclasses import dataclass
from datetime import timezone

from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth, TruncWeek, TruncYear

from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry
from apps.prescription.payment_models import PaymentReversal, PaymentSettlement

MAX_ROWS = 5000
SNAPSHOTS = {"exec-dashboard", "inv-balance", "inv-batch", "inv-expiry", "qa-quarantine", "qa-released"}
COLLECTIONS = {"sales-period", "sales-by-branch", "sales-refunds"}
AUDITS = {"audit-user", "audit-financial", "audit-clinical", "audit-config", "sec-audit-trail", "sec-permission-changes"}
MOVEMENTS = {"inv-movements", "audit-inventory"}
AVAILABLE = SNAPSHOTS | COLLECTIONS | AUDITS | MOVEMENTS


def availability(report_id):
    return {"available": report_id in AVAILABLE, "period_filter": report_id not in SNAPSHOTS,
            "availability_note": ("Current-state snapshot; reporting-window filters do not apply." if report_id in SNAPSHOTS
                                  else "Queries tenant source records within the selected window." if report_id in AVAILABLE
                                  else "Not implemented: no validated source-data query is available for this pack.")}


@dataclass(frozen=True)
class ReportData:
    basis: str
    columns: list[str]
    rows: list[list[str]]


def _bounded(queryset):
    rows = list(queryset[:MAX_ROWS + 1])
    if len(rows) > MAX_ROWS:
        raise ValueError("Report exceeds 5,000 rows. Choose a narrower reporting window; nothing was truncated.")
    return rows


def _period(queryset, field, window):
    if window:
        return queryset.filter(**{field + "__gte": window.period_start, field + "__lte": window.period_end})
    return queryset


def _authority(actor, tenant_id, capabilities):
    if not any(actor.has_capability(cap, tenant_id=tenant_id) for cap in capabilities):
        raise PermissionError("Report source access requires " + " or ".join(capabilities) + ".")


def query_report(report_id, tenant_id, actor, window):
    if report_id not in AVAILABLE:
        raise NotImplementedError("This report pack has no validated source-data query yet.")
    _authority(actor, tenant_id, ["reports.view"])
    if report_id in SNAPSHOTS and window:
        raise ValueError("This is a current-state snapshot; remove the reporting-window filters.")
    if report_id == "exec-dashboard":
        return None
    if report_id in COLLECTIONS:
        _authority(actor, tenant_id, ["payment.read", "payment.manage", "pos.shift.manage", "sales.read"])
        # These are collections, not accrual revenue, VAT, profit or unpaid orders.
        refunds = report_id == "sales-refunds"
        if refunds:
            qs = PaymentReversal.all_objects.filter(tenant_id=tenant_id, status="COMPLETED")
            qs = _period(qs, "completed_at", window)
            date_field, branch, currency, tender = "completed_at", "settlement__payment_tender__payment_intent__branch__code", "settlement__currency", "settlement__payment_tender__tender_type"
        else:
            qs = _period(PaymentSettlement.all_objects.filter(tenant_id=tenant_id), "settled_at", window)
            date_field, branch, currency, tender = "settled_at", "payment_tender__payment_intent__branch__code", "currency", "payment_tender__tender_type"
        trunc = {"HOURLY": TruncHour, "DAILY": TruncDay, "WEEKLY": TruncWeek, "MONTHLY": TruncMonth, "YEARLY": TruncYear}
        granularity = window.granularity if window else "DAILY"
        qs = qs.annotate(period=trunc[granularity](date_field, tzinfo=timezone.utc))
        groups = qs.values("period", branch, currency, tender).annotate(amount_total=Sum("amount"), events=Count("pk")).order_by("period", branch, currency, tender)
        rows = [[row["period"].isoformat(), row[branch], row[currency], row[tender], str(row["amount_total"]), str(row["events"])] for row in _bounded(groups)]
        return ReportData("Completed dispensing payment reversals; refunds dated by completion; currencies kept separate." if refunds
                          else "Gross settled dispensing payment collections; not accrual revenue. Refunds are reported separately. Retail carts and unpaid orders excluded.",
                          ["Period (UTC)", "Branch", "Currency", "Tender", "Refund amount" if refunds else "Gross collected", "Event count"], rows)
    if report_id in MOVEMENTS:
        _authority(actor, tenant_id, ["inventory.read", "inventory.manage"])
        qs = _period(InventoryLedgerEntry.all_objects.filter(tenant_id=tenant_id), "effective_timestamp", window)
        qs = qs.select_related("sku", "location", "branch", "inventory_batch").order_by("effective_timestamp", "pk")
        rows = [[r.effective_timestamp.isoformat(), r.branch.code, r.location.location_code, r.sku.sku_code, r.sku.display_name,
                 r.inventory_batch.manufacturer_batch_number if r.inventory_batch_id else "", r.entry_type,
                 str(r.quantity_delta), r.unit, str(r.base_quantity_delta), r.source_document_type, r.source_document_id] for r in _bounded(qs)]
        return ReportData("Immutable inventory events by effective timestamp. Reservation/release deltas are not physical stock movements.",
                          ["Effective timestamp", "Branch", "Location", "SKU code", "Item", "Batch", "Event type", "Quantity delta", "Unit", "Base quantity delta", "Source type", "Source ID"], rows)
    if report_id in SNAPSHOTS:
        _authority(actor, tenant_id, ["inventory.read", "inventory.manage"])
        qs = InventoryBalance.all_objects.filter(tenant_id=tenant_id).select_related("sku__package_definition", "location", "inventory_batch")
        if report_id == "qa-quarantine":
            qs = qs.filter(quarantined__gt=0)
        elif report_id == "qa-released":
            qs = qs.filter(available__gt=0, inventory_batch__quality_status="RELEASED", inventory_batch__recall_status="NONE")
        elif report_id == "inv-expiry":
            qs = qs.filter(on_hand__gt=0)
        rows = [[r.location.location_code, r.sku.sku_code, r.sku.display_name, r.sku.package_definition.unit_of_measure, r.inventory_batch.manufacturer_batch_number if r.inventory_batch_id else "",
                 str(r.inventory_batch.expiry_date) if r.inventory_batch_id else "", str(r.on_hand), str(r.reserved),
                 str(r.available), str(r.quarantined), r.inventory_batch.quality_status if r.inventory_batch_id else "UNKNOWN",
                 r.inventory_batch.recall_status if r.inventory_batch_id else "UNKNOWN"] for r in _bounded(qs.order_by("location_id", "sku_id", "inventory_batch_id"))]
        return ReportData("Current inventory projection at download time; not historical balances. Expiry report lists every positive-stock batch with its actual expiry.",
                          ["Location", "SKU code", "Item", "Stock unit", "Batch", "Expiry", "On hand", "Reserved", "Available", "Quarantined", "Quality", "Recall"], rows)
    _authority(actor, tenant_id, ["audit.read"])
    qs = _period(AuditEvent.all_objects.filter(tenant_id=tenant_id), "created_at", window)
    if report_id == "audit-financial":
        qs = qs.filter(model_name__iregex=r"payment|pricing|pos_shift")
    elif report_id == "audit-clinical":
        qs = qs.filter(model_name__iregex=r"prescription|clinical")
    elif report_id in {"audit-config", "sec-permission-changes"}:
        qs = qs.filter(model_name__iregex=r"identity|tenant|configuration")
    rows = [[r.created_at.isoformat(), str(r.actor_id or ""), r.action, r.model_name, r.object_id, r.outcome, r.correlation_id] for r in _bounded(qs.order_by("created_at", "pk"))]
    return ReportData("Immutable tenant audit events. Sensitive event metadata is deliberately excluded.",
                      ["Timestamp", "Actor ID", "Action", "Model", "Object ID", "Outcome", "Correlation ID"], rows)
