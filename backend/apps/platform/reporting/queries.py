"""Report-specific, tenant-bound facts. Planned packs never become fake snapshots."""
from dataclasses import dataclass
from datetime import timezone

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth, TruncWeek, TruncYear

from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry
from apps.pos_transactions.models import RetailCashReceipt, RetailCashRefund
from apps.prescription.payment_models import PaymentReversal, PaymentSettlement

from .operator_source_queries import OPERATOR_REPORTS, OPERATOR_SNAPSHOTS, query_operator_report
from .source_queries import SOURCE_REPORTS, SOURCE_SNAPSHOTS, query_source_report

MAX_ROWS = 5000
SNAPSHOTS = {"exec-dashboard", "inv-balance", "inv-batch", "inv-expiry", "qa-quarantine", "qa-released"} | SOURCE_SNAPSHOTS | OPERATOR_SNAPSHOTS
COLLECTIONS = {"sales-period", "sales-by-branch", "sales-refunds"}
AUDITS = {"audit-user", "audit-financial", "audit-clinical", "audit-config", "sec-audit-trail", "sec-permission-changes"}
MOVEMENTS = {"inv-movements", "audit-inventory"}
AVAILABLE = SNAPSHOTS | COLLECTIONS | AUDITS | MOVEMENTS | SOURCE_REPORTS | OPERATOR_REPORTS


def _missing_prerequisites(report_id):
    if report_id in {"fin-gl", "fin-trial-balance", "fin-ap", "fin-ar", "fin-vat", "fin-profitability", "exec-revenue", "exec-receivables", "exec-payables"}:
        return "Validated financial posting, accrual/tax/receivable/payable and reconciliation ledgers are required. Orders, receipts and settled collections are not substitute accounting records."
    if report_id in {"inv-valuation", "exec-inventory-value"}:
        return "A validated stock cost/valuation method and immutable cost layers are required; retail prices are not inventory costs."
    if report_id == "fin-cash-book":
        return "An approved bank/cash ledger and reconciliation contract is required; current till X/Z reports cover drawers only."
    if report_id.startswith("an-"):
        return "Validated historical observation coverage, analytical definitions and forecast/backtest methodology are required. No estimated demand, revenue or model accuracy is fabricated."
    if report_id.startswith("cd-"):
        return "A legally reviewed controlled-drug register/event taxonomy, running-balance/reconciliation and authorised export contract is required. General inventory movements do not certify the statutory register."
    if report_id in {"reg-ppb", "reg-pv", "reg-gdp-gsp"}:
        return "Approved regulator submission/ADR or GDP/GSP evidence contracts and external acceptance are required. Manual internal records do not constitute regulator certification."
    if report_id in {"sec-secret-scan", "sec-dependency-posture", "sec-tenant-isolation"}:
        return "Source-linked scanner/isolation evidence ingestion and validated pass/fail provenance are required; audit counts are not security certification."
    if report_id in {"qa-capa", "qa-deviations", "exec-quality-kpis"}:
        return "Governed CAPA/deviation and validated KPI definitions/source records are required; quarantine stock alone is not a complete quality system."
    if report_id in {"sales-by-insurer", "crm-insurance-util"}:
        return "Approved insurer claim/eligibility acceptance, payer attribution and reconciled claim facts are required; manual insurer templates do not prove utilisation or reimbursement."
    if report_id == "log-routes":
        return "A governed route/stop/execution source and utilisation definition are required; dispatch records alone do not establish routes."
    if report_id == "proc-supplier-performance":
        return "Validated promised-date, delivered quantity and quality/return denominator definitions are required before calculating OTIF or supplier scores."
    return "A validated report-specific source contract, time basis and reconciliation/acceptance tests are still required."


def availability(report_id):
    return {"available": report_id in AVAILABLE, "period_filter": report_id not in SNAPSHOTS,
            "availability_note": ("Current-state snapshot; reporting-window filters do not apply." if report_id in SNAPSHOTS
                                  else "Queries tenant source records within the selected window." if report_id in AVAILABLE
                                  else "Not implemented: " + _missing_prerequisites(report_id))}


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
    if report_id in SOURCE_REPORTS:
        return query_source_report(report_id, tenant_id, actor, window)
    if report_id in OPERATOR_REPORTS:
        return query_operator_report(report_id, tenant_id, actor, window)
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
        groups = qs.values("period", branch, currency, tender).annotate(amount_total=Sum("amount"), events=Count("pk"))
        rows = [[row["period"].isoformat(), row[branch], row[currency], row[tender], str(row["amount_total"]), str(row["events"]), "CLINICAL"] for row in _bounded(groups)]
        retail_model = RetailCashRefund if refunds else RetailCashReceipt
        retail_date = "completed_at" if refunds else "settled_at"
        retail_branch = "register__location__code" if refunds else "transaction__branch__code"
        retail = _period(retail_model.all_objects.filter(tenant_id=tenant_id), retail_date, window)
        retail_groups = retail.annotate(period=trunc[granularity](retail_date, tzinfo=timezone.utc)).values(
            "period", retail_branch, "currency").annotate(amount_total=Sum("amount"), events=Count("pk"))
        rows.extend([[row["period"].isoformat(), row[retail_branch], row["currency"], "CASH", str(row["amount_total"]), str(row["events"]), "RETAIL"] for row in _bounded(retail_groups)])
        if len(rows) > MAX_ROWS:
            raise ValueError("Report exceeds 5,000 rows. Choose a narrower reporting window; nothing was truncated.")
        rows.sort(key=lambda row: (row[0], row[1], row[2], row[3], row[6]))
        return ReportData("Completed clinical payment reversals and receipt-linked retail cash refunds; dated by completion. Refund execution branch is the cash-out till; currencies kept separate." if refunds
                          else "Gross settled clinical and retail payment collections; not accrual revenue. Refunds are reported separately. Unpaid carts and orders excluded; currencies and source channels kept separate.",
                          ["Period (UTC)", "Branch", "Currency", "Tender", "Refund amount" if refunds else "Gross collected", "Event count", "Source channel"], rows)
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
        qs = qs.filter(Q(model_name__iregex=r"payment|pricing|pos_shift|retail.*refund|pos.*transaction") | Q(action__startswith="RETAIL_"))
    elif report_id == "audit-clinical":
        qs = qs.filter(model_name__iregex=r"prescription|clinical")
    elif report_id == "audit-config":
        qs = qs.filter(Q(model_name__iregex=r"identity|tenant|configuration") | Q(model_name__in=["User", "Role", "UserRole", "AttributePolicy"]) | Q(action__startswith="IDENTITY_"))
    elif report_id == "sec-permission-changes":
        # Historic identity services wrote bare model names; newer services may
        # use app-qualified names. Preserve both and the canonical action family.
        qs = qs.filter(Q(action__startswith="IDENTITY_") | Q(model_name__in=["User", "Role", "UserRole", "AttributePolicy"])
                       | Q(model_name__iregex=r"^(identity\.|tenancy\.|configuration\.)(User|Role|UserRole|AttributePolicy|Tenant)"))
    rows = [[r.created_at.isoformat(), str(r.actor_id or ""), r.action, r.model_name, r.object_id, r.outcome, r.correlation_id] for r in _bounded(qs.order_by("created_at", "pk"))]
    return ReportData("Immutable tenant audit events. Sensitive event metadata is deliberately excluded.",
                      ["Timestamp", "Actor ID", "Action", "Model", "Object ID", "Outcome", "Correlation ID"], rows)
