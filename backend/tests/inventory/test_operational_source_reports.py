from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import Customer
from apps.identity.models import Role, User, UserRole
from apps.inventory.recalls.models import RegulatoryAlert, RegulatoryTenantImpact
from apps.inventory.services import InventoryLedgerService, StocktakeService
from apps.platform.reporting.services import ReportWindow
from apps.platform.reporting.source_queries import SOURCE_REPORTS, SOURCE_SNAPSHOTS, query_source_report
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    Supplier,
    SupplierQualification,
    SupplierReturn,
    SupplierReturnLine,
    ThreeWayMatch,
)
from apps.sales.models import DeliveryRecord, DispatchOrder

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_reporter(tenant_a):
    actor = User.objects.create_user(username="operational-source-reporter", tenant=tenant_a)
    role = Role.all_objects.create(tenant=tenant_a, code="SOURCE_REPORTS", name="Source report reader", capabilities=["reports.view", "inventory.manage", "procurement.read", "sales.read"])
    UserRole.all_objects.create(tenant=tenant_a, user=actor, role=role)
    return actor


@pytest.mark.parametrize("report_id", sorted(SOURCE_REPORTS))
def test_each_operational_pack_queries_real_empty_sources(report_id, tenant_a, source_reporter):
    report = query_source_report(report_id, tenant_a.pk, source_reporter, None)
    assert report.columns
    assert report.basis
    assert report.rows == []


@pytest.mark.parametrize("report_id", sorted(SOURCE_REPORTS))
def test_operational_pack_rejects_cross_tenant_authority(report_id, tenant_a, tenant_b, source_reporter):
    with pytest.raises(PermissionError):
        query_source_report(report_id, tenant_b.pk, source_reporter, None)


@pytest.mark.parametrize("report_id", sorted(SOURCE_SNAPSHOTS))
def test_operational_snapshot_rejects_historical_window(report_id, tenant_a, source_reporter):
    with pytest.raises(ValueError, match="current-state"):
        query_source_report(report_id, tenant_a.pk, source_reporter, ReportWindow("2026-10-01T00:00:00Z", "2026-10-12T23:59:59Z", "DAILY"))


def test_inventory_observation_reports_contain_actual_facts(tenant_a, branch, inventory_location, sku, inventory_batch, source_reporter):
    InventoryLedgerService.post_entry(tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
                                     entry_type="RECEIPT", quantity_delta=100, unit="tablet", base_quantity_delta=100, effective_timestamp=timezone.now(),
                                     source_document_type="OPENING_STOCK", source_document_id="opening-source", idempotency_key="source-opening")
    session = StocktakeService.open_stocktake(tenant=tenant_a, branch=branch, locations=[inventory_location], scope="FULL", creator=source_reporter)
    StocktakeService.record_count(session=session, location=inventory_location, sku=sku, batch=inventory_batch, counted_quantity=95, counter=source_reporter)
    counts = query_source_report("inv-cycle-count", tenant_a.pk, source_reporter, None)
    assert counts.rows[0][9] == "95.0000"
    dead = query_source_report("inv-dead-stock", tenant_a.pk, source_reporter, None)
    assert dead.rows[0][6] == "NO_RECORDED_ISSUE"
    InventoryLedgerService.post_entry(tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
                                     entry_type="ISSUE", quantity_delta=-4, unit="tablet", base_quantity_delta=-4, effective_timestamp=timezone.now(),
                                     source_document_type="RETAIL_SALE", source_document_id="receipt-source", idempotency_key="source-issue")
    velocity = query_source_report("inv-velocity", tenant_a.pk, source_reporter, None)
    # Aggregated Decimal scale differs between SQLite and PostgreSQL; the
    # quantity contract is exact units, not backend-specific string padding.
    assert Decimal(velocity.rows[0][4]) == Decimal("4")
    InventoryLedgerService.post_entry(tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
                                     entry_type="ISSUE", quantity_delta=Decimal("-0.125"), unit="tablet", base_quantity_delta=Decimal("-0.125"), effective_timestamp=timezone.now(),
                                     source_document_type="RETAIL_SALE", source_document_id="fractional-source", idempotency_key="source-fractional-issue")
    fractional = query_source_report("inv-velocity", tenant_a.pk, source_reporter, None)
    assert Decimal(fractional.rows[0][4]) == Decimal("4.125")
    assert fractional.rows[0][5] == "2"
    assert query_source_report("inv-dead-stock", tenant_a.pk, source_reporter, None).rows == []
    trace = query_source_report("reg-traceability", tenant_a.pk, source_reporter, None)
    assert len(trace.rows) == 3
    assert "receipt-source" in str(trace.rows)
    assert trace.rows[0][6] == ""
    assert "Patient identifiers are not exported" in trace.basis


def test_procurement_and_quality_packs_export_recorded_source_values(tenant_a, branch, sku, source_reporter):
    today = timezone.localdate()
    supplier = Supplier.all_objects.create(tenant=tenant_a, supplier_code="REP-SUP", legal_name="Report Supplier")
    requisition = PurchaseRequisition.all_objects.create(tenant=tenant_a, requisition_number="REP-REQ", requesting_branch=branch, requester=source_reporter, requested_delivery_date=today)
    PurchaseRequisitionLine.all_objects.create(tenant=tenant_a, requisition=requisition, sku=sku, requested_quantity=20, approved_quantity=15)
    order = PurchaseOrder.all_objects.create(tenant=tenant_a, po_number="REP-PO", supplier=supplier, ordering_branch=branch, order_date=today - timezone.timedelta(days=5), expected_delivery_date=today, total_gross=Decimal("1500"))
    po_line = PurchaseOrderLine.all_objects.create(tenant=tenant_a, purchase_order=order, sku=sku, ordered_quantity=15, purchase_unit="tablet", unit_price=Decimal("100"), total_price=Decimal("1500"))
    receipt = GoodsReceipt.all_objects.create(tenant=tenant_a, grn_number="REP-GRN", purchase_order=order, supplier=supplier, receiving_branch=branch, received_by=source_reporter,
                                              delivery_note_number="REP-DN", arrival_time=timezone.now(), status="RECEIVED")
    line = GoodsReceiptLine.all_objects.create(tenant=tenant_a, goods_receipt=receipt, po_line=po_line, sku=sku, delivered_quantity=15, accepted_quantity=10, quarantined_quantity=5)
    batch = ReceivedBatch.all_objects.create(tenant=tenant_a, grn_line=line, sku=sku, manufacturer_batch_number="REP-BATCH", expiry_date=today + timezone.timedelta(days=90), received_quantity=15, temperature_excursion=True)
    ThreeWayMatch.all_objects.create(tenant=tenant_a, purchase_order=order, goods_receipt=receipt, invoice_reference="REP-INVOICE", matching_status="VARIANCE_FLAGGED", price_variance=Decimal("12.50"))
    returned = SupplierReturn.all_objects.create(tenant=tenant_a, return_number="REP-RETURN", goods_receipt=receipt, supplier=supplier, status="CREDIT_PENDING", reason="Received quality hold")
    SupplierReturnLine.all_objects.create(tenant=tenant_a, supplier_return=returned, sku=sku, batch=batch, quantity=5)
    SupplierQualification.all_objects.create(tenant=tenant_a, supplier=supplier, qualification_type="WHOLESALE_DEALER_LICENCE", licence_number="REP-LICENCE", effective_date=today, expiry_date=today + timezone.timedelta(days=30), verification_basis="MANUAL_INTERNAL_VERIFICATION")
    reports = {report_id: query_source_report(report_id, tenant_a.pk, source_reporter, None) for report_id in SOURCE_REPORTS if report_id.startswith("proc-") or report_id in {"qa-temperature", "qa-supplier"}}
    assert all(report.rows for report in reports.values())
    assert reports["proc-lead-time"].rows[0][7] == "5"
    assert reports["proc-price-variance"].rows[0][7] == "12.50"
    assert reports["proc-returns"].rows[0][4] == "CREDIT_PENDING"
    assert reports["qa-temperature"].rows[0][7] == "True"
    assert reports["qa-supplier"].rows[0][8] == "MANUAL_INTERNAL_VERIFICATION"


def test_delivery_and_local_recall_sources_do_not_assert_external_certification(tenant_a, branch, source_reporter):
    customer = Customer.all_objects.create(tenant=tenant_a, customer_number="REP-CUSTOMER", legal_name="Report Customer", customer_type="PHARMACY")
    dispatch = DispatchOrder.all_objects.create(tenant=tenant_a, dispatch_number="REP-DISPATCH", branch=branch, customer=customer, expected_delivery_date=timezone.localdate())
    DeliveryRecord.all_objects.create(tenant=tenant_a, dispatch_order=dispatch, customer=customer, status="DELIVERED", delivered_at=timezone.now(), signature_ref="private-object-reference", photo_ref="private-photo-reference", proof_type="SIGNATURE")
    for report_id in {"log-shipments", "log-pod", "log-delivery"}:
        report = query_source_report(report_id, tenant_a.pk, source_reporter, None)
        assert report.rows
        assert "REP-DISPATCH" in str(report.rows)
        assert "private-object-reference" not in str(report.rows)
        assert "private-photo-reference" not in str(report.rows)
    alert = RegulatoryAlert.objects.create(alert_reference="REP-ALERT", title="Local recall", severity="HIGH", affected_batches=["REP-BATCH"], product_name="Report product")
    RegulatoryTenantImpact.all_objects.create(tenant=tenant_a, alert=alert, affected_batches=["REP-BATCH"], quarantined_stock_count=3)
    for report_id in {"qa-recalls", "exec-regulatory-alerts"}:
        report = query_source_report(report_id, tenant_a.pk, source_reporter, None)
        assert report.rows[0][9] == "LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED"
        assert "not regulator certification" in report.basis


def test_report_calendar_days_use_nairobi_date_across_utc_midnight(tenant_a, branch, source_reporter):
    # 21:30 UTC is already the following business date in Nairobi.
    observed = datetime(2026, 10, 13, 21, 30, tzinfo=UTC)
    supplier = Supplier.all_objects.create(tenant=tenant_a, supplier_code="MIDNIGHT-SUP", legal_name="Supplier")
    order = PurchaseOrder.all_objects.create(tenant=tenant_a, po_number="MIDNIGHT-PO", supplier=supplier,
        ordering_branch=branch, order_date=date(2026, 10, 9), expected_delivery_date=date(2026, 10, 13))
    GoodsReceipt.all_objects.create(tenant=tenant_a, grn_number="MIDNIGHT-GRN", purchase_order=order,
        supplier=supplier, receiving_branch=branch, received_by=source_reporter,
        arrival_time=observed, status="RECEIVED")
    customer = Customer.all_objects.create(tenant=tenant_a, customer_number="MIDNIGHT-CUSTOMER", legal_name="Customer", customer_type="PHARMACY")
    dispatch = DispatchOrder.all_objects.create(tenant=tenant_a, dispatch_number="MIDNIGHT-DISPATCH",
        branch=branch, customer=customer, expected_delivery_date=date(2026, 10, 13))
    DeliveryRecord.all_objects.create(tenant=tenant_a, dispatch_order=dispatch, customer=customer,
        status="DELIVERED", delivered_at=observed, proof_type="SIGNATURE")
    with timezone.override("Africa/Nairobi"):
        lead = query_source_report("proc-lead-time", tenant_a.pk, source_reporter, None)
        assert lead.rows[0][7:] == ["5", "LATE"]
        delivery = query_source_report("log-delivery", tenant_a.pk, source_reporter, None)
        assert delivery.rows[0][7] == "LATE"
