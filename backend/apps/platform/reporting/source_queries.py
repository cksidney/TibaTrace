"""Operational report packs backed by their named domain source records.

No operational document is promoted to an accounting ledger or regulatory
certification. Each pack states its actual observation/time basis.
"""

from datetime import timedelta

from django.db.models import Count, Max, OuterRef, Subquery, Sum
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryReservation, StocktakeCount
from apps.inventory.recalls.models import RegulatoryTenantImpact
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseRequisitionLine,
    ReceivedBatch,
    SupplierQualification,
    SupplierReturnLine,
    ThreeWayMatch,
)
from apps.sales.models import DeliveryRecord, DispatchOrder

SOURCE_SNAPSHOTS = {"inv-dead-stock", "inv-fefo"}
SOURCE_REPORTS = SOURCE_SNAPSHOTS | {
    "inv-cycle-count", "inv-velocity", "proc-requisitions", "proc-orders", "proc-grn",
    "proc-lead-time", "proc-price-variance", "proc-returns", "qa-temperature", "qa-supplier",
    "qa-recalls", "exec-regulatory-alerts", "log-shipments", "log-pod", "log-delivery", "reg-traceability",
}


def _text(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def query_source_report(report_id, tenant_id, actor, window):
    # Imported at execution time: queries.py owns the public report contract.
    from .queries import ReportData, _authority, _bounded, _period

    if report_id not in SOURCE_REPORTS:
        raise NotImplementedError("No validated operational source query exists for this report.")
    _authority(actor, tenant_id, ["reports.view"])
    if report_id in SOURCE_SNAPSHOTS and window:
        raise ValueError("This is a current-state operational snapshot; remove reporting-window filters.")

    def result(basis, columns, rows):
        return ReportData(basis, columns, [[_text(value) for value in row] for row in rows])

    if report_id in {"inv-cycle-count", "inv-velocity", "inv-dead-stock", "inv-fefo", "reg-traceability"}:
        _authority(actor, tenant_id, ["inventory.read", "inventory.manage"])
        if report_id == "inv-cycle-count":
            qs = _period(StocktakeCount.all_objects.filter(tenant_id=tenant_id, session__tenant_id=tenant_id), "timestamp", window)
            qs = qs.select_related("session__branch", "location", "sku", "batch").order_by("timestamp", "pk")
            return result("Physical count observations by latest observation timestamp; first counts, recounts and voids retained. Variances are posted only where session status is POSTED. Not a write-off authorisation.",
                          ["Session ID", "Branch", "Scope", "Session state", "Location", "SKU", "Batch", "Observation time", "Expected at observation", "First count", "Recount", "Current physical count", "Variance", "Approved count", "Voided"],
                          [[r.session_id, r.session.branch.code, r.session.scope, r.session.status, r.location.location_code, r.sku.sku_code,
                            r.batch.manufacturer_batch_number if r.batch_id else None, r.timestamp, r.expected_quantity, r.first_count,
                            r.recount, r.counted_quantity, r.variance, r.final_approved_count, r.voided] for r in _bounded(qs)])
        if report_id == "inv-velocity":
            qs = _period(InventoryLedgerEntry.all_objects.filter(tenant_id=tenant_id, entry_type="ISSUE", base_quantity_delta__lt=0), "effective_timestamp", window)
            groups = qs.values("branch__code", "location__location_code", "sku__sku_code", "sku__package_definition__unit_of_measure").annotate(
                quantity=Sum("base_quantity_delta"), events=Count("pk"), latest=Max("effective_timestamp")).order_by("branch__code", "location__location_code", "sku__sku_code")
            return result("Observed physical ISSUE quantity within the selected window (positive units issued); transfers/reservations excluded. No fabricated demand forecast or arbitrary fast/slow thresholds; quantities remain in each SKU's base unit.",
                          ["Branch", "Location", "SKU", "Base unit", "Units issued", "Issue events", "Latest issue"],
                          [[r["branch__code"], r["location__location_code"], r["sku__sku_code"], r["sku__package_definition__unit_of_measure"], -r["quantity"], r["events"], r["latest"]] for r in _bounded(groups)])
        if report_id == "inv-dead-stock":
            now = timezone.now()
            last_issue = InventoryLedgerEntry.all_objects.filter(tenant_id=tenant_id, sku_id=OuterRef("sku_id"), location_id=OuterRef("location_id"), entry_type="ISSUE", effective_timestamp__lte=now).order_by("-effective_timestamp").values("effective_timestamp")[:1]
            qs = InventoryBalance.all_objects.filter(tenant_id=tenant_id, on_hand__gt=0).annotate(last_issue=Subquery(last_issue)).select_related("location", "sku", "inventory_batch").order_by("location_id", "sku_id", "inventory_batch_id")
            rows = []
            for r in _bounded(qs):
                if r.last_issue is None or r.last_issue < now - timedelta(days=90):
                    rows.append([r.location.location_code, r.sku.sku_code, r.inventory_batch.manufacturer_batch_number if r.inventory_batch_id else None,
                                 r.on_hand, r.available, r.last_issue, "NO_RECORDED_ISSUE" if r.last_issue is None else "NO_ISSUE_IN_90_DAYS", now])
            return result("Current positive stock with no recorded SKU/location ISSUE in the last 90 days, as of download. No recorded issue is unknown history, not proof of 90-day age; this is a review candidate list, not a valuation or write-off instruction.",
                          ["Location", "SKU", "Batch", "On hand", "Available", "Latest recorded issue", "Review basis", "As of"], rows)
        if report_id == "inv-fefo":
            qs = InventoryReservation.all_objects.filter(tenant_id=tenant_id, status__in=["PENDING", "ALLOCATED", "PARTIALLY_FULFILLED"]).select_related("branch", "source_location", "sku", "batch").order_by("source_location_id", "sku_id", "batch__expiry_date", "pk")
            return result("Current outstanding reservations ordered by allocated batch expiry within location/SKU. Missing batches remain explicit. This review supports FEFO planning; it is not historical FEFO compliance certification.",
                          ["Reservation ID", "Branch", "Location", "SKU", "State", "Batch", "Expiry", "Requested", "Allocated", "Unit", "Source"],
                          [[r.pk, r.branch.code, r.source_location.location_code, r.sku.sku_code, r.status, r.batch.manufacturer_batch_number if r.batch_id else None,
                            r.batch.expiry_date if r.batch_id else None, r.requested_quantity, r.allocated_quantity, r.unit, r.source_document] for r in _bounded(qs)])
        qs = _period(InventoryLedgerEntry.all_objects.filter(tenant_id=tenant_id), "effective_timestamp", window).select_related("branch", "location", "sku", "inventory_batch__source_received_batch__grn_line__goods_receipt__supplier").order_by("effective_timestamp", "pk")
        rows = []
        for r in _bounded(qs):
            batch = r.inventory_batch
            received = batch.source_received_batch if batch and batch.source_received_batch_id else None
            grn = received.grn_line.goods_receipt if received else None
            rows.append([r.effective_timestamp, r.branch.code, r.location.location_code, r.sku.sku_code,
                         batch.manufacturer_batch_number if batch else None, batch.expiry_date if batch else None,
                         grn.grn_number if grn and grn.tenant_id == r.tenant_id else None,
                         grn.supplier.supplier_code if grn and grn.tenant_id == r.tenant_id and grn.supplier.tenant_id == r.tenant_id else None,
                         r.entry_type, r.base_quantity_delta, r.source_document_type, r.source_document_id, r.source_line_id])
        return result("Recorded batch-linked ledger genealogy and source document references by effective timestamp. Opening stock with no GRN is labelled by blank source fields; reservations are not physical movements. Patient identifiers are not exported.",
                      ["Effective time", "Branch", "Location", "SKU", "Batch", "Expiry", "Source GRN", "Supplier", "Event", "Base delta", "Source type", "Source document", "Source line"], rows)

    if report_id.startswith("proc-") or report_id in {"qa-temperature", "qa-supplier"}:
        _authority(actor, tenant_id, ["procurement.read", "procurement.manage"])
        if report_id == "proc-requisitions":
            qs = _period(PurchaseRequisitionLine.all_objects.filter(tenant_id=tenant_id, requisition__tenant_id=tenant_id, sku__tenant_id=tenant_id), "requisition__created_at", window).select_related("requisition__requesting_branch", "sku").order_by("requisition__created_at", "pk")
            return result("Requisition line source records; window selects requisition creation time. Current approval and outstanding quantities are shown, not recreated historical status.",
                          ["Requisition", "Created", "Branch", "Document state", "SKU", "Requested", "Approved", "Outstanding", "Purchase unit", "Line state"],
                          [[r.requisition.requisition_number, r.requisition.created_at, r.requisition.requesting_branch.code, r.requisition.status, r.sku.sku_code, r.requested_quantity, r.approved_quantity, r.outstanding_quantity, r.purchase_unit, r.status] for r in _bounded(qs)])
        if report_id == "proc-orders":
            qs = _period(PurchaseOrder.all_objects.filter(tenant_id=tenant_id, supplier__tenant_id=tenant_id, ordering_branch__tenant_id=tenant_id), "created_at", window).select_related("supplier", "ordering_branch").order_by("created_at", "pk")
            return result("Recorded purchase-order commitments; window selects document creation time. Currency-specific document values are not supplier liabilities, payments or an accounts-payable ledger.",
                          ["PO", "Created", "Order date", "Expected delivery", "Branch", "Supplier", "State", "Currency", "Net", "Tax", "Gross", "Revision"],
                          [[r.po_number, r.created_at, r.order_date, r.expected_delivery_date, r.ordering_branch.code, r.supplier.supplier_code, r.status, r.currency, r.total_net, r.total_tax, r.total_gross, r.revision_number] for r in _bounded(qs)])
        if report_id == "proc-grn":
            qs = _period(GoodsReceiptLine.all_objects.filter(tenant_id=tenant_id, goods_receipt__tenant_id=tenant_id, sku__tenant_id=tenant_id), "goods_receipt__arrival_time", window).select_related("goods_receipt__purchase_order", "goods_receipt__receiving_branch", "sku").order_by("goods_receipt__arrival_time", "pk")
            return result("GRN line records by recorded arrival time, including explicitly labelled draft/rejected records. Physical delivered/accepted/quarantined/rejected quantities are source facts, not invoice accounting.",
                          ["GRN", "Arrival", "PO", "Branch", "State", "SKU", "Delivered", "Accepted", "Quarantined", "Rejected"],
                          [[r.goods_receipt.grn_number, r.goods_receipt.arrival_time, r.goods_receipt.purchase_order.po_number, r.goods_receipt.receiving_branch.code, r.goods_receipt.status, r.sku.sku_code, r.delivered_quantity, r.accepted_quantity, r.quarantined_quantity, r.rejected_quantity] for r in _bounded(qs)])
        if report_id == "proc-lead-time":
            qs = _period(GoodsReceipt.all_objects.filter(tenant_id=tenant_id, purchase_order__tenant_id=tenant_id, supplier__tenant_id=tenant_id).exclude(status__in=["DRAFT", "CANCELLED"]), "arrival_time", window).select_related("purchase_order", "supplier").order_by("arrival_time", "pk")
            return result("Recorded order-date-to-GRN-arrival calendar days for non-draft/non-cancelled receipts. Each partial arrival is separate; negative source-date differences remain visible rather than silently corrected.",
                          ["Supplier", "PO", "Order date", "Expected delivery", "GRN", "Arrival", "Receipt state", "Lead days", "Arrival relative to expected"],
                          [[r.supplier.supplier_code, r.purchase_order.po_number, r.purchase_order.order_date, r.purchase_order.expected_delivery_date, r.grn_number, r.arrival_time, r.status,
                            (timezone.localtime(r.arrival_time).date() - r.purchase_order.order_date).days,
                            "ON_OR_BEFORE" if timezone.localtime(r.arrival_time).date() <= r.purchase_order.expected_delivery_date else "LATE"] for r in _bounded(qs)])
        if report_id == "proc-price-variance":
            qs = _period(ThreeWayMatch.all_objects.filter(tenant_id=tenant_id, purchase_order__tenant_id=tenant_id, goods_receipt__tenant_id=tenant_id), "created_at", window).select_related("purchase_order", "goods_receipt").order_by("created_at", "pk")
            return result("Recorded three-way-match exceptions by match creation time. Price variance is the stored reviewed source value; no synthetic invoice line prices or ledger posting are inferred.",
                          ["Created", "PO", "GRN", "Invoice reference", "Match state", "Currency", "Quantity variance", "Recorded price variance"],
                          [[r.created_at, r.purchase_order.po_number, r.goods_receipt.grn_number, r.invoice_reference, r.matching_status, r.purchase_order.currency, r.quantity_variance, r.price_variance] for r in _bounded(qs)])
        if report_id == "proc-returns":
            qs = _period(SupplierReturnLine.all_objects.filter(tenant_id=tenant_id, supplier_return__tenant_id=tenant_id, sku__tenant_id=tenant_id), "supplier_return__created_at", window).select_related("supplier_return__supplier", "supplier_return__goods_receipt", "sku", "batch").order_by("supplier_return__created_at", "pk")
            return result("Supplier-return line records by return creation time. Document state shows credit-pending/closed where recorded; it does not assert a credit note or supplier payment.",
                          ["Return", "Created", "Supplier", "GRN", "State", "SKU", "Batch", "Quantity"],
                          [[r.supplier_return.return_number, r.supplier_return.created_at, r.supplier_return.supplier.supplier_code, r.supplier_return.goods_receipt.grn_number, r.supplier_return.status, r.sku.sku_code, r.batch.manufacturer_batch_number if r.batch_id else None, r.quantity] for r in _bounded(qs)])
        if report_id == "qa-temperature":
            qs = _period(ReceivedBatch.all_objects.filter(tenant_id=tenant_id, grn_line__tenant_id=tenant_id, temperature_excursion=True), "grn_line__goods_receipt__arrival_time", window).select_related("grn_line__goods_receipt", "sku").order_by("grn_line__goods_receipt__arrival_time", "pk")
            return result("Recorded receiving temperature-excursion flags by GRN arrival. No sensor temperature, duration or calibration reading is invented; investigate the source inspection evidence.",
                          ["GRN", "Arrival", "SKU", "Batch", "Expiry", "Received", "Quality state", "Excursion flagged"],
                          [[r.grn_line.goods_receipt.grn_number, r.grn_line.goods_receipt.arrival_time, r.sku.sku_code, r.manufacturer_batch_number, r.expiry_date, r.received_quantity, r.quality_status, r.temperature_excursion] for r in _bounded(qs)])
        qs = _period(SupplierQualification.all_objects.filter(tenant_id=tenant_id, supplier__tenant_id=tenant_id), "created_at", window).select_related("supplier").order_by("created_at", "pk")
        return result("Supplier qualification evidence by creation time and current recorded verification state. Manual internal verification is not a live regulator lookup; licence validity dates are preserved.",
                      ["Supplier", "Supplier state", "Qualification", "Licence", "Authority", "Effective", "Expiry", "Verification state", "Verification basis", "Verified at"],
                      [[r.supplier.supplier_code, r.supplier.status, r.qualification_type, r.licence_number, r.issuing_authority, r.effective_date, r.expiry_date, r.verification_status, r.verification_basis, r.verified_at] for r in _bounded(qs)])

    if report_id in {"qa-recalls", "exec-regulatory-alerts"}:
        _authority(actor, tenant_id, ["inventory.read", "inventory.manage"])
        qs = _period(RegulatoryTenantImpact.all_objects.filter(tenant_id=tenant_id), "created_at", window).select_related("alert").order_by("created_at", "pk")
        return result("Tenant-specific recorded regulatory-alert impacts by impact creation time. Alert truth labels distinguish local workflow from authenticated regulator feeds; matching/closure is not regulator certification.",
                      ["Impact created", "Alert reference", "Regulator", "Severity", "Alert state", "Impact state", "Affected batches", "Quarantined stock records", "Prior supply tracing needed", "Truth label"],
                      [[r.created_at, r.alert.alert_reference, r.alert.issuing_regulator, r.alert.severity, r.alert.status, r.state, "; ".join(r.affected_batches), r.quarantined_stock_count, r.prior_dispense_trace_required, r.alert.truth_label] for r in _bounded(qs)])

    _authority(actor, tenant_id, ["sales.read", "sales.manage"])
    if report_id == "log-shipments":
        qs = _period(DispatchOrder.all_objects.filter(tenant_id=tenant_id, customer__tenant_id=tenant_id), "created_at", window).select_related("branch", "customer").order_by("created_at", "pk")
        return result("Dispatch source documents created within the selected window, showing current state and recorded dates. This is not live carrier GPS/telemetry.",
                      ["Dispatch", "Created", "Branch", "Customer number", "State", "Carrier", "Vehicle", "Dispatch date", "Expected delivery", "Temperature requirement"],
                      [[r.dispatch_number, r.created_at, r.branch.code, r.customer.customer_number, r.status, r.carrier, r.vehicle, r.dispatch_date, r.expected_delivery_date, r.temperature_requirement] for r in _bounded(qs)])
    qs = _period(DeliveryRecord.all_objects.filter(tenant_id=tenant_id, dispatch_order__tenant_id=tenant_id), "created_at", window).select_related("dispatch_order", "customer").order_by("created_at", "pk")
    return result("Recorded delivery attempts created within the selected window, with current outcome, actual delivery timestamp and presence of stored POD evidence. No external carrier or recipient-signature authenticity is asserted.",
                  ["Delivery ID", "Created", "Dispatch", "Customer number", "State", "Expected delivery", "Delivered at", "Timing outcome", "POD reference present", "Signature reference present"],
                  [[r.pk, r.created_at, r.dispatch_order.dispatch_number, r.customer.customer_number, r.status, r.dispatch_order.expected_delivery_date, r.delivered_at,
                    "UNKNOWN" if not r.delivered_at or not r.dispatch_order.expected_delivery_date else "ON_OR_BEFORE" if timezone.localtime(r.delivered_at).date() <= r.dispatch_order.expected_delivery_date else "LATE",
                    bool(r.photo_ref or r.proof_type), bool(r.signature_ref)] for r in _bounded(qs)])
