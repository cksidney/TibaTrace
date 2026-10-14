"""Narrow, attributable source observations; never substitute financial ledgers."""
from uuid import UUID

from django.db.models import Count

from apps.customers.models import Customer
from apps.fhir.models import FHIRIdempotencyRecord
from apps.pos_shift.cash_control import CashControlService
from apps.pos_shift.models import RegisterSession
from apps.pos_transactions.models import RetailCashReceipt
from apps.prescription.models import MedicineSupply, PatientMedicationHistory
from apps.sales.models import SalesOrder

MODULE_SNAPSHOTS = {"exec-cash-position"}
MODULE_REPORTS = MODULE_SNAPSHOTS | {"sales-by-customer", "crm-growth", "crm-patient-history", "hr-productivity", "sec-fhir-idempotency"}


def _branch_scope(queryset, actor, field):
    scope = (actor.metadata or {}).get("branch_ids")
    if scope is None:
        return queryset
    if not isinstance(scope, list):
        raise PermissionError("Invalid branch scope; no cross-branch report is authorised.")
    try:
        branches = [UUID(str(value)) for value in scope]
    except (ValueError, TypeError, AttributeError) as exc:
        raise PermissionError("Invalid branch scope; no cross-branch report is authorised.") from exc
    return queryset.filter(**{field + "__in": branches})


def query_module_report(report_id, tenant_id, actor, window):
    from .queries import MAX_ROWS, ReportData, _authority, _bounded, _period
    _authority(actor, tenant_id, ["reports.view"])
    if report_id not in MODULE_REPORTS:
        raise NotImplementedError("No validated module source query is available.")
    if report_id in MODULE_SNAPSHOTS and window:
        raise ValueError("This is a current-state snapshot; remove reporting-window filters.")

    def result(basis, columns, rows):
        def value(item):
            return "" if item is None else item.isoformat() if hasattr(item, "isoformat") else str(item)
        return ReportData(basis, columns, [[value(v) for v in row] for row in rows])

    if report_id == "sales-by-customer":
        _authority(actor, tenant_id, ["sales.read", "sales.manage"])
        qs = _period(SalesOrder.all_objects.filter(tenant_id=tenant_id, customer__tenant_id=tenant_id, branch__tenant_id=tenant_id), "created_at", window)
        qs = _branch_scope(qs, actor, "branch_id").select_related("customer", "branch").order_by("created_at", "pk")
        return result("Commercial order cohorts by creation time with current fulfilment state and document totals. Amounts are orders, not collected cash, posted revenue, receivables or profit; currencies stay separate. Customer contact information excluded.",
            ["Order number", "Created at", "Customer number", "Customer type", "Branch", "Current status", "Currency", "Order subtotal", "Order tax", "Order total"],
            [[r.order_number, r.created_at, r.customer.customer_number, r.customer.customer_type, r.branch.code, r.status, r.currency, r.subtotal, r.tax_total, r.total] for r in _bounded(qs)])
    if report_id == "crm-growth":
        _authority(actor, tenant_id, ["sales.read", "sales.manage"])
        qs = _period(Customer.all_objects.filter(tenant_id=tenant_id), "created_at", window).order_by("created_at", "pk")
        return result("Customer creation cohorts and their current status. This does not infer historical activation, dormancy, retention, or revenue growth. Names, addresses and contact information excluded.",
            ["Customer number", "Created at", "Customer type", "Current status"],
            [[r.customer_number, r.created_at, r.customer_type, r.status] for r in _bounded(qs)])
    if report_id == "crm-patient-history":
        _authority(actor, tenant_id, ["patients.read", "patients.manage"])
        _authority(actor, tenant_id, ["clinical.read", "prescriptions.clinical_review", "prescriptions.pharmacist_verify"])
        qs = _period(PatientMedicationHistory.all_objects.filter(tenant_id=tenant_id, patient__tenant_id=tenant_id, dispensing_episode__tenant_id=tenant_id), "supplied_at", window)
        qs = _branch_scope(qs, actor, "dispensing_episode__branch_id").select_related("patient", "dispensing_episode__branch", "supplied_sku__package_definition", "inventory_batch").order_by("supplied_at", "pk")
        return result("Recorded medication-history entries by supplied timestamp, including appended return/reversal records with their recorded status. Quantities are individual entries, not a net supply total, purchase revenue or verified treatment outcome. Patient numbers support authorised continuity of care; names, DOB, contact details, instructions and free text excluded.",
            ["History ID", "Patient number", "Supplied at", "Branch", "SKU code", "Medicine snapshot", "Quantity", "Unit", "Batch", "Expiry", "Recorded status", "Source"],
            [[r.pk, r.patient.patient_number, r.supplied_at, r.dispensing_episode.branch.code, r.supplied_sku.sku_code if r.supplied_sku_id else "", r.medicine_name_snapshot,
              r.quantity, r.supplied_sku.package_definition.unit_of_measure, r.inventory_batch.manufacturer_batch_number if r.inventory_batch_id else "", r.inventory_batch.expiry_date if r.inventory_batch_id else None, r.status, r.source] for r in _bounded(qs)])
    if report_id == "hr-productivity":
        _authority(actor, tenant_id, ["pos.shift.manage"])
        _authority(actor, tenant_id, ["clinical.read", "prescriptions.clinical_review", "prescriptions.pharmacist_verify"])
        clinical = _branch_scope(_period(MedicineSupply.all_objects.filter(tenant_id=tenant_id, episode__tenant_id=tenant_id), "supplied_at", window), actor, "episode__branch_id")
        retail = _branch_scope(_period(RetailCashReceipt.all_objects.filter(tenant_id=tenant_id, transaction__tenant_id=tenant_id), "settled_at", window), actor, "transaction__branch_id")
        clinical = clinical.values("supplied_by_id", "episode__branch_id", "status").annotate(events=Count("pk")).order_by("supplied_by_id", "episode__branch_id", "status")
        retail = retail.values("created_by_id", "transaction__branch_id").annotate(events=Count("pk")).order_by("created_by_id", "transaction__branch_id")
        rows = [["CLINICAL_SUPPLY", r["supplied_by_id"], r["episode__branch_id"], r["status"], r["events"]] for r in _bounded(clinical)]
        rows.extend([["RETAIL_CASH_RECEIPT", r["created_by_id"], r["transaction__branch_id"], "SETTLED", r["events"]] for r in _bounded(retail)])
        if len(rows) > MAX_ROWS:
            raise ValueError("Report exceeds 5,000 rows. Narrow the window; nothing was truncated.")
        return result("Observed accountable-actor event counts: clinical supply by supplied time and retail cash receipts by settlement time, kept separate. Not staff productivity, efficiency, licence certification or a human ranking; status retained and no patient identity or money exported.",
            ["Source channel", "Actor ID", "Branch ID", "Status", "Recorded event count"], rows)
    if report_id == "exec-cash-position":
        _authority(actor, tenant_id, ["pos.shift.manage"])
        qs = _branch_scope(RegisterSession.all_objects.filter(tenant_id=tenant_id, register__tenant_id=tenant_id, state__in=["OPEN", "CLOSING"]), actor, "register__location_id")
        qs = qs.select_related("register__location", "business_day").order_by("register_id", "pk")
        rows = []
        for r in _bounded(qs):
            cash = CashControlService.expected_cash(session=r)
            rows.append([r.pk, r.register.location.code, r.register.code, r.business_day.business_date, r.state, r.register.currency, cash.opening,
                         cash.cash_sales, cash.cash_in, cash.cash_out, cash.cash_refunds, cash.expected])
        return result("Open/closing till drawer projections observed during report generation using the cash-control reconciliation service. Expected cash is not a physical count, bank balance, posted cash book or frozen Z closure; no unexplained variance is inferred. Currencies kept separate.",
            ["Session ID", "Branch", "Register", "Business date", "State", "Currency", "Opening cash", "Cash sales (clinical net / retail gross)", "Cash in", "Cash out", "Retail cash refunds", "Expected drawer"], rows)
    _authority(actor, tenant_id, ["audit.read", "identity.manage"])
    qs = _period(FHIRIdempotencyRecord.all_objects.filter(tenant_id=tenant_id), "created_at", window).order_by("created_at", "pk")
    return result("Recorded tenant FHIR idempotency observations by request creation time and stored current state. This is not proof of all exchanges, duplicate attempts, delivery acceptance or interoperability certification. Raw keys, request hashes, resource IDs and clinical content excluded.",
        ["Record ID", "Created at", "Updated at", "Resource type", "Operation", "Current state", "Response status", "Actor ID"],
        [[r.pk, r.created_at, r.updated_at, r.resource_type, r.operation, r.state, r.response_status, r.actor_id] for r in _bounded(qs)])
