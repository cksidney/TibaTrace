# ruff: noqa: F811
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from tests.test_hq_queue_completion import opening
from tests.test_pos_retail_transactions import create_draft, world  # noqa: F401
from tests.test_stock_transfer_api import transfer_world  # noqa: F401

from apps.identity.models import User
from apps.inventory.count_upload import stocktake_template, upload_counts
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryBatchCost,
    InventoryChangeRequest,
    InventoryLedgerEntry,
    StocktakeCount,
    StockTransferLine,
)
from apps.inventory.operations import decide_change, request_change, valuation
from apps.inventory.services import StocktakeService, StockTransferService
from apps.medicines.models import BranchAssortment, CommercialSKU
from apps.medicines.onboarding import StaleSetupReview
from apps.medicines.onboarding_completion import release_opening_setup, stage_opening_setup
from apps.medicines.onboarding_counts import import_opening_counts
from apps.pricing.models import PriceBookVersion
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def reviewer(world):
    return User.objects.create_user(username="inventory-independent", tenant=world["tenant"], is_superuser=True)


def change(world, kind="WRITE_OFF", **payload):
    batch = InventoryBatch.all_objects.get(tenant=world["tenant"], manufacturer_batch_number="RETAIL-AVAILABLE-1")
    return request_change(
        tenant=world["tenant"],
        actor=world["operator"],
        kind=kind,
        payload={"batch_id": str(batch.pk), "location_id": str(world["store"].pk), "quantity": "2", **payload},
        reason="Investigated physical evidence",
        idempotency_key="request-1",
    )


def test_writeoff_waits_for_independent_approval_and_retry_posts_once(world):
    item = change(world)
    balance = InventoryBalance.all_objects.get(location=world["store"])
    assert balance.on_hand == 8
    with pytest.raises(ValidationError, match="separate"):
        decide_change(change=item, actor=world["operator"], approve=True, reason="Verified")
    other = reviewer(world)
    decide_change(change=item, actor=other, approve=True, reason="Verified disposal")
    decide_change(change=item, actor=other, approve=True, reason="Verified disposal")
    balance.refresh_from_db()
    assert balance.on_hand == 6
    assert InventoryLedgerEntry.all_objects.filter(source_document_type="APPROVED_INVENTORY_CHANGE").count() == 1


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "1.00001", "999999999999999"])
def test_invalid_writeoff_quantities_fail_before_request(world, quantity):
    with pytest.raises(ValidationError):
        change(world, quantity=quantity)
    assert not InventoryChangeRequest.all_objects.exists()


def test_reserved_stock_cannot_be_written_off_and_rejection_has_no_effect(world):
    item = change(world, quantity="8")
    balance = InventoryBalance.all_objects.get(location=world["store"])
    balance.reserved = 2
    balance.available = 6
    balance.save()
    other = reviewer(world)
    with pytest.raises(ValidationError, match="unreserved"):
        decide_change(change=item, actor=other, approve=True, reason="Review")
    item.refresh_from_db()
    assert item.status == "PENDING"
    decide_change(change=item, actor=other, approve=False, reason="Reserved for patient")
    balance.refresh_from_db()
    assert balance.on_hand == 8


def test_cost_approval_values_actual_units_and_freezes_future_movements(world):
    assert valuation(world["tenant"].pk)["unvalued_lines"] == 1
    item = change(world, kind="COST", unit_cost="12.3456", evidence="Supplier invoice; one sales pack")
    other = reviewer(world)
    decide_change(change=item, actor=other, approve=True, reason="Matched invoice to sales unit")
    result = valuation(world["tenant"].pk)
    assert result["complete"] and Decimal(result["known_value"]) == Decimal("98.7648")
    cost = InventoryBatchCost.all_objects.get()
    cost.unit_cost = 999
    with pytest.raises(ValidationError, match="immutable"):
        cost.save()
    removal = request_change(
        tenant=world["tenant"],
        actor=world["operator"],
        kind="DESTRUCTION",
        payload={"batch_id": str(cost.batch_id), "location_id": str(world["store"].pk), "quantity": "1"},
        reason="Destruction evidence",
        idempotency_key="destroy",
    )
    decide_change(change=removal, actor=other, approve=True, reason="Witnessed")
    assert InventoryLedgerEntry.all_objects.get(
        source_document_id=str(removal.pk)
    ).cost_snapshot.value_delta == Decimal("-12.3456")


def test_change_cannot_reference_another_tenant_or_retry_different_payload(world):
    item = change(world)
    with pytest.raises(ValidationError, match="different"):
        change(world, quantity="3")
    other = Tenant.objects.create(name="Other", slug="other-stock")
    with pytest.raises(ValidationError, match="tenant"):
        request_change(
            tenant=other,
            actor=world["operator"],
            kind="WRITE_OFF",
            payload=item.payload,
            reason="Wrong tenant",
            idempotency_key="other",
        )


def test_count_upload_preview_atomicity_retry_and_no_overwrite(world):
    session = StocktakeService.open_stocktake(
        tenant=world["tenant"],
        branch=world["branch"],
        locations=[world["store"]],
        scope="FULL",
        creator=world["operator"],
    )
    batch = InventoryBatch.all_objects.get(manufacturer_batch_number="RETAIL-AVAILABLE-1")
    row = {
        "session_id": str(session.pk),
        "location_id": str(world["store"].pk),
        "sku_id": str(world["sku"].pk),
        "batch_id": str(batch.pk),
        "counted_quantity": "7",
        "reason": "Physical observation",
    }
    assert "expected_quantity" not in stocktake_template(session)
    upload_counts(session=session, actor=world["operator"], rows=[row], dry_run=True)
    assert not StocktakeCount.all_objects.filter(session=session).exists()
    with pytest.raises(ValidationError):
        upload_counts(session=session, actor=world["operator"], rows=[row, {**row, "batch_id": "bad"}], dry_run=False)
    assert not StocktakeCount.all_objects.filter(session=session).exists()
    assert upload_counts(session=session, actor=world["operator"], rows=[row], dry_run=False)["new_counts"] == 1
    assert upload_counts(session=session, actor=world["operator"], rows=[row], dry_run=False)["existing_counts"] == 1
    with pytest.raises(ValidationError, match="recount"):
        upload_counts(session=session, actor=world["operator"], rows=[{**row, "counted_quantity": "8"}], dry_run=False)
    StocktakeService.post_variances(session=session, approver=reviewer(world))
    assert InventoryBalance.all_objects.get(location=world["store"]).on_hand == 7


def test_opening_count_upload_preserves_price_and_rejects_stale_sheet(world):
    item, _, _ = opening(world)
    row = {
        "item_id": str(item.pk),
        "expected_updated_at": item.updated_at.isoformat(),
        "counted_quantity": "5",
        "counted_on": timezone.localdate().isoformat(),
        "batch_number": "ACTUAL-5",
        "expiry_date": (timezone.localdate() + timezone.timedelta(days=300)).isoformat(),
    }
    import_opening_counts(tenant_id=item.tenant_id, actor=world["operator"], rows=[row], dry_run=True)
    item.refresh_from_db()
    assert item.review["counted_quantity"] == "3"
    import_opening_counts(tenant_id=item.tenant_id, actor=world["operator"], rows=[row], dry_run=False)
    item.refresh_from_db()
    assert Decimal(item.review["counted_quantity"]) == 5 and Decimal(item.review["confirmed_price"]) == 125
    with pytest.raises(StaleSetupReview):
        import_opening_counts(tenant_id=item.tenant_id, actor=world["operator"], rows=[row], dry_run=False)


def test_supply_can_enter_retail_without_creating_clinical_identity(world):
    item, quarantine, values = opening(world)
    item.proposed_sku_code = "SUP-001"
    item.source_name = "Reviewed gauze"
    item.review.update(item_kind="SUPPLY", master_catalogue_code="", batches=[], confirmed_cost="10")
    item.save()
    values["sku_id"] = None
    count = CommercialSKU.all_objects.filter(product_kind="MEDICINE").count()
    staged = stage_opening_setup(
        item=item, actor=world["operator"], expected_updated_at=item.updated_at.isoformat(), values=values
    )
    sku = CommercialSKU.all_objects.get(pk=staged.completion["sku_id"])
    assert sku.product_kind == "SUPPLY" and sku.manufactured_product is None and not sku.is_dispensable
    assert not BranchAssortment.all_objects.get(sku=sku).is_dispensable
    assert CommercialSKU.all_objects.filter(product_kind="MEDICINE").count() == count
    batch = InventoryBatch.all_objects.get(sku=sku)
    assert batch.lot_kind == "INTERNAL" and batch.expiry_date is None
    other = reviewer(world)
    version = PriceBookVersion.all_objects.get(pk=staged.completion["price_version_id"])
    version.status = "ACTIVE"
    version.approved_by = other
    version.save()
    release_opening_setup(
        item=staged,
        actor=other,
        expected_updated_at=staged.updated_at.isoformat(),
        destination_location_id=world["store"].pk,
        reason="Checked physical stock and acquisition cost",
    )
    assert InventoryBalance.all_objects.get(sku=sku, location=world["store"]).available == 3
    assert InventoryBatchCost.all_objects.get(batch=batch).unit_cost == 10
    draft = create_draft(world)
    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {"device_id": "POS-RETAIL-01", "sku_id": str(sku.pk), "quantity": "1"},
        format="json",
    )
    assert response.status_code == 201, response.data


def test_loss_closure_records_remaining_units_without_another_stock_debit(transfer_world):
    w = transfer_world
    transfer = StockTransferService.request_transfer(
        tenant=w["tenant"],
        transfer_number="LOSS-1",
        source_branch=w["source_location"].branch,
        dest_branch=w["destination_location"].branch,
        source_location=w["source_location"],
        dest_location=w["destination_location"],
        requested_by=w["requester"],
        lines_data=[{"sku": w["sku"], "quantity": Decimal("4")}],
        reason="Rebalance",
    )
    StockTransferService.approve_transfer(transfer=transfer, approver=w["approver"])
    StockTransferService.allocate_and_dispatch(transfer=transfer, dispatcher=w["requester"])
    transfer.refresh_from_db()
    line = StockTransferLine.all_objects.get(tenant=w["tenant"], transfer=transfer)
    StockTransferService.receive_transfer(
        transfer=transfer,
        receiver=w["receiver"],
        received_lines_data=[
            {
                "line_id": line.pk,
                "batch_id": w["batch"].pk,
                "quantity": Decimal("3"),
                "damaged": 0,
                "discrepancy_reason": "One missing",
            }
        ],
        idempotency_key="received-3",
    )
    transfer.refresh_from_db()
    item = request_change(
        tenant=w["tenant"],
        actor=w["receiver"],
        kind="TRANSFER_LOSS",
        payload={"transfer_id": str(transfer.pk)},
        reason="Carrier investigation confirmed one lost unit",
        idempotency_key="loss",
    )
    count = InventoryLedgerEntry.all_objects.count()
    decide_change(change=item, actor=w["approver"], approve=True, reason="Confirmed loss evidence")
    line.refresh_from_db()
    transfer.refresh_from_db()
    assert transfer.status == "CLOSED" and line.lost_quantity == 1 and line.received_quantity == 3
    assert InventoryLedgerEntry.all_objects.count() == count
    assert InventoryBalance.all_objects.get(location=w["source_location"]).on_hand == 6


def test_inventory_api_permissions_and_generic_write_protection(world):
    item = change(world)
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="no-stock-authority", tenant=world["tenant"]))
    assert client.get("/api/inventory/changes/").status_code == 403
    client.force_authenticate(world["operator"])
    assert client.patch(f"/api/inventory/changes/{item.pk}/", {"status": "POSTED"}, format="json").status_code == 405
    assert client.get("/api/inventory/changes/valuation/").status_code == 200
    assert (
        client.post(
            f"/api/inventory/changes/{item.pk}/decide/", {"approve": True, "reason": "Own request"}, format="json"
        ).status_code
        == 400
    )


@pytest.fixture
def received_stock(world):
    from apps.inventory.models import InventoryLocation
    from apps.inventory.receiving import stage_quarantine
    from apps.procurement.models import (
        GoodsReceipt,
        GoodsReceiptLine,
        PurchaseOrder,
        PurchaseOrderLine,
        ReceivedBatch,
        Supplier,
    )

    tenant = world["tenant"]
    supplier = Supplier.all_objects.create(tenant=tenant, supplier_code="RETURN-SUP", legal_name="Actual supplier")
    order = PurchaseOrder.all_objects.create(
        tenant=tenant,
        supplier=supplier,
        po_number="RETURN-PO",
        ordering_branch=world["branch"],
        order_date=timezone.localdate(),
        expected_delivery_date=timezone.localdate(),
    )
    order_line = PurchaseOrderLine.all_objects.create(
        tenant=tenant,
        purchase_order=order,
        sku=world["sku"],
        ordered_quantity=5,
        received_quantity=5,
        unit_price=20,
        total_price=100,
    )
    receipt = GoodsReceipt.all_objects.create(
        tenant=tenant,
        grn_number="RETURN-GRN",
        purchase_order=order,
        supplier=supplier,
        receiving_branch=world["branch"],
        received_by=world["operator"],
        delivery_note_number="DEL-5",
        arrival_time=timezone.now(),
    )
    line = GoodsReceiptLine.all_objects.create(
        tenant=tenant,
        goods_receipt=receipt,
        po_line=order_line,
        sku=world["sku"],
        delivered_quantity=5,
        quarantined_quantity=5,
    )
    received = ReceivedBatch.all_objects.create(
        tenant=tenant,
        grn_line=line,
        sku=world["sku"],
        manufacturer_batch_number="ACTUAL-RETURN-BATCH",
        expiry_date=timezone.localdate() + timezone.timedelta(days=200),
        received_quantity=5,
        quarantined_quantity=5,
        quality_status="QUARANTINED",
    )
    location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=world["branch"],
        location_code="RETURN-QUAR",
        name="Quarantine custody",
        location_type="QUARANTINE",
        quarantine_capability=True,
    )
    stage_quarantine(
        tenant=tenant, batch=received, location=location, actor=world["operator"], reason="Counted five actual units"
    )
    return receipt, received, location


def test_supplier_return_posts_once_and_requires_independent_credit_reconciliation(world, received_stock):
    from apps.procurement.services.returns_service import SupplierReturnService as Service

    receipt, batch, location = received_stock
    item = Service.request_return(
        tenant=world["tenant"],
        return_number="RETURN-2",
        goods_receipt=receipt,
        reason="Supplier accepted damaged outer packs",
        requested_by=world["operator"],
        expected_credit="40",
    )
    Service.add_return_line(supplier_return=item, sku=world["sku"], quantity=2, batch=batch, source_location=location)
    with pytest.raises(ValidationError, match="independent"):
        Service.approve(supplier_return=item, approver=world["operator"])
    other = reviewer(world)
    Service.approve(supplier_return=item, approver=other)
    Service.dispatch(supplier_return=item, actor=world["operator"])
    Service.dispatch(supplier_return=item, actor=world["operator"])
    assert InventoryBalance.all_objects.get(location=location).on_hand == 3
    assert InventoryLedgerEntry.all_objects.filter(source_document_type="SUPPLIER_RETURN").count() == 1
    with pytest.raises(ValidationError, match="difference"):
        Service.record_credit(supplier_return=item, actor=world["operator"], amount="39", reference="CREDIT-2")
    Service.record_credit(
        supplier_return=item,
        actor=world["operator"],
        amount="39",
        reference="CREDIT-2",
        variance_reason="One shilling freight deduction agreed",
    )
    with pytest.raises(ValidationError, match="separate"):
        Service.close_credit(supplier_return=item, actor=world["operator"])
    closed = Service.close_credit(supplier_return=item, actor=other)
    assert closed.status == "CLOSED" and closed.credit_amount == Decimal("39")


def test_supplier_return_allowance_spans_all_claims_and_api_failure_is_atomic(world, received_stock):
    from apps.procurement.models import SupplierReturn
    from apps.procurement.services.returns_service import SupplierReturnService as Service

    receipt, batch, location = received_stock
    item = Service.request_return(
        tenant=world["tenant"],
        return_number="RETURN-4",
        goods_receipt=receipt,
        reason="Recall",
        requested_by=world["operator"],
    )
    Service.add_return_line(supplier_return=item, sku=world["sku"], quantity=4, batch=batch, source_location=location)
    second = Service.request_return(
        tenant=world["tenant"],
        return_number="RETURN-OVER",
        goods_receipt=receipt,
        reason="Recall",
        requested_by=world["operator"],
    )
    with pytest.raises(ValidationError, match="remaining"):
        Service.add_return_line(
            supplier_return=second, sku=world["sku"], quantity=2, batch=batch, source_location=location
        )
    response = world["client"].post(
        "/api/procurement/supplier-returns/",
        {
            "goods_receipt": str(receipt.pk),
            "return_number": "ATOMIC-FAIL",
            "reason": "Recall",
            "expected_credit": "40",
            "lines": [{"sku": str(world["sku"].pk), "quantity": 1}, {"sku": str(world["sku"].pk), "quantity": 2}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert not SupplierReturn.all_objects.filter(return_number="ATOMIC-FAIL").exists()


def test_partial_quality_release_moves_quarantine_stock_without_duplicate_receipt(world, received_stock):
    from apps.inventory.receiving import release_received_stock

    receipt, batch, location = received_stock
    batch.accepted_quantity = 2
    batch.quality_status = "PARTIALLY_RELEASED"
    batch.save()
    for _ in range(2):
        release_received_stock(
            tenant=world["tenant"], received_batch=batch, receiving_location=world["store"], actor=world["operator"]
        )
    assert InventoryBalance.all_objects.get(location=location).on_hand == 3
    batch.accepted_quantity = 5
    batch.quality_status = "RELEASED"
    batch.save()
    released = release_received_stock(
        tenant=world["tenant"], received_batch=batch, receiving_location=world["store"], actor=world["operator"]
    )
    assert InventoryBalance.all_objects.get(location=world["store"], inventory_batch=released).on_hand == 5
    assert InventoryBalance.all_objects.get(location=location).on_hand == 0
    assert InventoryLedgerEntry.all_objects.filter(source_document_type="RECEIVED_BATCH_QUARANTINE").count() == 1
