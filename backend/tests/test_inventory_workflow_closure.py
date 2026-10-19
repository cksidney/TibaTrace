# ruff: noqa: F811
"""Regression coverage for physical custody, reservations and projection integrity."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from tests.test_inventory_gap_closure import received_stock, reviewer  # noqa: F401
from tests.test_pos_retail_transactions import world  # noqa: F401

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import InventoryLedgerService, InventoryReservationService
from apps.procurement.services.batch_quality_service import BatchQualityDecisionService
from apps.procurement.services.returns_service import SupplierReturnService

pytestmark = pytest.mark.django_db


def reserve(world, quantity=4):
    return InventoryReservationService.reserve_stock(
        tenant=world["tenant"],
        branch=world["branch"],
        source_location=world["store"],
        sku=world["sku"],
        requested_quantity=Decimal(quantity),
        purpose="AUDIT",
        actor=world["operator"],
        idempotency_key="audit-reservation",
    )


def test_integrity_check_accepts_real_receipt_and_reservation(world):  # noqa: F811
    batch = InventoryBatch.all_objects.get(tenant=world["tenant"])
    InventoryBalance.all_objects.filter(tenant=world["tenant"]).delete()
    InventoryLedgerService.post_entry(
        tenant=world["tenant"],
        branch=world["branch"],
        location=world["store"],
        sku=world["sku"],
        inventory_batch=batch,
        entry_type="RECEIPT",
        quantity_delta=8,
        base_quantity_delta=8,
        unit="pack",
        effective_timestamp=timezone.now(),
        source_document_type="AUDIT_RECEIPT",
        source_document_id="audit-receipt",
        idempotency_key="audit-receipt",
    )
    reserve(world)
    balance = InventoryBalance.all_objects.get(tenant=world["tenant"])
    assert (balance.on_hand, balance.reserved, balance.available) == (8, 4, 4)
    call_command("check_inventory_integrity", tenant_id=str(world["tenant"].pk), stdout=StringIO(), stderr=StringIO())


def test_partially_fulfilled_reservation_can_release_remaining_units(world):  # noqa: F811
    reservation = reserve(world)
    batch = InventoryBatch.all_objects.get(tenant=world["tenant"])
    InventoryReservationService.fulfill_reservation(
        reservation=reservation,
        quantity=Decimal(1),
        inventory_batch=batch,
        actor=world["operator"],
        idempotency_key="audit-fulfil",
    )
    reservation.refresh_from_db()
    assert reservation.status == "PARTIALLY_FULFILLED"
    InventoryReservationService.release_reservation(reservation=reservation, actor=world["operator"])
    balance = InventoryBalance.all_objects.get(tenant=world["tenant"])
    assert balance.reserved == 0


def test_quality_release_requires_independent_quality_decision(world, received_stock):  # noqa: F811
    _, batch, _ = received_stock
    response = world["client"].post(
        f"/api/procurement/received-batches/{batch.pk}/release/",
        {
            "quantity": 5,
            "reason": "Audit release without quality decision",
            "inventory_location": str(world["store"].pk),
        },
        format="json",
    )
    assert response.status_code in (400, 403), response.data


def test_return_dispatch_and_release_cannot_invent_replacement_stock(world, received_stock):  # noqa: F811
    receipt, batch, location = received_stock
    item = SupplierReturnService.request_return(
        tenant=world["tenant"],
        return_number="AUDIT-RETURN",
        goods_receipt=receipt,
        reason="Rejected units returned physically",
        requested_by=world["operator"],
        expected_credit=40,
    )
    SupplierReturnService.add_return_line(
        supplier_return=item, sku=world["sku"], quantity=2, batch=batch, source_location=location
    )
    other = reviewer(world)
    SupplierReturnService.approve(supplier_return=item, approver=other)
    SupplierReturnService.dispatch(supplier_return=item, actor=world["operator"])
    BatchQualityDecisionService.record_decision(
        batch=batch,
        inspector=other,
        decision_by=other,
        outcome="APPROVE_FOR_RELEASE",
        reason="Independent physical quality review for the remaining custody",
    )
    response = world["client"].post(
        f"/api/procurement/received-batches/{batch.pk}/release/",
        {"quantity": 5, "reason": "Audit release after two left custody", "inventory_location": str(world["store"].pk)},
        format="json",
    )
    if response.status_code not in (400, 403):
        stock = sum(
            InventoryBalance.all_objects.filter(
                inventory_batch__manufacturer_batch_number="ACTUAL-RETURN-BATCH"
            ).values_list("on_hand", flat=True)
        )
        assert stock <= 3, f"{stock} on hand after receiving 5 and returning 2; response={response.status_code}"


def qualify(receipt, actor):
    from apps.procurement.models import SupplierQualification

    receipt.supplier.status = "ACTIVE"
    receipt.supplier.save()
    for kind in ["BUSINESS_REGISTRATION", "WHOLESALE_DEALER_LICENCE"]:
        SupplierQualification.all_objects.create(
            tenant_id=receipt.tenant_id,
            supplier=receipt.supplier,
            qualification_type=kind,
            licence_number=f"FIXTURE-{kind}",
            issuing_authority="Synthetic fixture",
            effective_date=timezone.localdate(),
            expiry_date=timezone.localdate() + timezone.timedelta(days=300),
            verification_status="VERIFIED",
            verified_by=actor,
        )


def test_independent_release_of_remaining_return_custody_and_retry(world, received_stock):  # noqa: F811
    from apps.inventory.receiving import release_received_stock
    from apps.procurement.services.receiving_service import GoodsReceivingService

    receipt, batch, location = received_stock
    other = reviewer(world)
    qualify(receipt, other)
    item = SupplierReturnService.request_return(
        tenant=world["tenant"],
        return_number="RETURN-RELEASE",
        goods_receipt=receipt,
        reason="Damaged outer packs",
        requested_by=world["operator"],
        expected_credit=40,
    )
    SupplierReturnService.add_return_line(
        supplier_return=item, sku=world["sku"], quantity=2, batch=batch, source_location=location
    )
    SupplierReturnService.approve(supplier_return=item, approver=other)
    SupplierReturnService.dispatch(supplier_return=item, actor=world["operator"])
    BatchQualityDecisionService.record_decision(
        batch=batch,
        inspector=other,
        decision_by=other,
        outcome="APPROVE_FOR_RELEASE",
        reason="Checked remaining three physical packs",
    )
    args = dict(
        batch=batch,
        released_by=other,
        reason="Verified three remain",
        quantity=3,
        receiving_location=world["store"],
        idempotency_key="release-remaining",
    )
    result = GoodsReceivingService.release_batch(**args)
    release_received_stock(
        tenant=world["tenant"], received_batch=result, receiving_location=world["store"], actor=other
    )
    GoodsReceivingService.release_batch(**args)
    assert (
        InventoryBalance.all_objects.filter(
            inventory_batch__manufacturer_batch_number=batch.manufacturer_batch_number
        ).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("on_hand"))["total"]
        == 3
    )
    assert (
        InventoryBalance.all_objects.get(
            location=world["store"], inventory_batch__manufacturer_batch_number=batch.manufacturer_batch_number
        ).available
        == 3
    )
    with pytest.raises(ValidationError, match="different command"):
        GoodsReceivingService.release_batch(**{**args, "quantity": 1})


def test_quality_hold_requires_explicit_evidenced_reinspection(world, received_stock):  # noqa: F811
    from django.core.exceptions import ValidationError

    _, batch, _ = received_stock
    other = reviewer(world)
    held = BatchQualityDecisionService.record_decision(
        batch=batch, inspector=other, decision_by=other, outcome="DOCUMENTATION_HOLD", reason="Delivery evidence absent"
    )
    with pytest.raises(ValidationError, match="supersede"):
        BatchQualityDecisionService.record_decision(
            batch=batch, inspector=other, decision_by=other, outcome="APPROVE_FOR_RELEASE", reason="New inspection"
        )
    new = BatchQualityDecisionService.record_decision(
        batch=batch,
        inspector=other,
        decision_by=other,
        outcome="APPROVE_FOR_RELEASE",
        reason="Original delivery evidence verified",
        evidence_reference="Fixture proof",
        supersedes_id=held.pk,
    )
    assert new.revision == 2 and new.supersedes_id == held.pk
    held.refresh_from_db()
    assert held.decision == "DOCUMENTATION_HOLD"
    assert BatchQualityDecisionService.decision_for(batch=batch).pk == new.pk


def test_repair_does_not_invent_stock_for_reservations_and_recovers_missing_projection(world):  # noqa: F811
    from django.db.models import Sum

    from apps.inventory.reconciliation import reconcile

    batch = InventoryBatch.all_objects.get(tenant=world["tenant"])
    # The fixture starts with a projection; replace it with real source events.
    InventoryBalance.all_objects.filter(tenant=world["tenant"]).delete()
    InventoryLedgerService.post_entry(
        tenant=world["tenant"],
        branch=world["branch"],
        location=world["store"],
        sku=world["sku"],
        inventory_batch=batch,
        entry_type="RECEIPT",
        quantity_delta=8,
        base_quantity_delta=8,
        unit="pack",
        effective_timestamp=timezone.now(),
        source_document_type="FIXTURE",
        source_document_id="8",
        idempotency_key="real-8",
    )
    reserve(world)
    InventoryBalance.all_objects.filter(tenant=world["tenant"]).delete()
    assert reconcile(world["tenant"], repair=True)
    balance = InventoryBalance.all_objects.get(tenant=world["tenant"])
    assert (balance.on_hand, balance.reserved, balance.available) == (8, 4, 4)
    assert (
        InventoryLedgerEntry.all_objects.filter(tenant=world["tenant"], entry_type="RECEIPT").aggregate(
            total=Sum("base_quantity_delta")
        )["total"]
        == 8
    )
    assert not reconcile(world["tenant"])


def test_due_partial_reservation_expires_once_without_overrelease(world):  # noqa: F811
    from apps.inventory.models import InventoryReservation
    from apps.inventory.tasks import process_tenant_expiry

    reservation = reserve(world)
    batch = InventoryBatch.all_objects.get(tenant=world["tenant"])
    args = dict(
        reservation=reservation,
        quantity=Decimal(1),
        inventory_batch=batch,
        actor=world["operator"],
        idempotency_key="one-unit",
    )
    InventoryReservationService.fulfill_reservation(**args)
    InventoryReservationService.fulfill_reservation(**args)
    InventoryReservation.all_objects.filter(pk=reservation.pk).update(
        expiry_time=timezone.now() - timezone.timedelta(seconds=1)
    )
    assert process_tenant_expiry.run(str(world["tenant"].pk))["expired_reservations"] == 1
    assert process_tenant_expiry.run(str(world["tenant"].pk))["expired_reservations"] == 0
    assert InventoryBalance.all_objects.get(tenant=world["tenant"]).reserved == 0


def test_barcode_conversion_at_pos_is_once_in_base_units_and_evidenced(world):  # noqa: F811
    from tests.test_pos_retail_transactions import create_draft

    from apps.inventory.models import BarcodeMaster
    from apps.pos_transactions.models import PosTransactionLine

    mapping = BarcodeMaster.all_objects.get(tenant=world["tenant"])
    mapping.pack_conversion = 2
    mapping.save()
    draft = create_draft(world)
    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/scan/",
        {"device_id": "POS-RETAIL-01", "barcode": mapping.barcode, "quantity": "2"},
        format="json",
    )
    assert response.status_code == 201, response.data
    line = PosTransactionLine.all_objects.get(transaction_id=draft["id"])
    assert line.quantity == 4
    assert Decimal(line.unit_evidence[0]["pack_conversion"]) == 2


def test_replenishment_accounts_for_pending_demand_and_retry(world):  # noqa: F811
    from apps.inventory import replenishment
    from apps.inventory.models import ReplenishmentRecommendation
    from apps.procurement.services.procurement_service import ProcurementService

    policy = replenishment.configure(
        tenant=world["tenant"],
        actor=world["operator"],
        branch=world["branch"],
        sku=world["sku"],
        destination=world["store"],
        safety_stock=5,
        reorder_point=10,
        target_stock=20,
        order_multiple=5,
    )
    assert replenishment.refresh(world["tenant"]) == 1
    item = ReplenishmentRecommendation.all_objects.get(status="PENDING")
    assert item.recommended_quantity == 15  # 8 available, rounded to full five-unit packs.
    args = dict(item=item, actor=world["operator"], approve=True, reason="Physical shelf demand reviewed")
    result = replenishment.decide(**args)
    again = replenishment.decide(**args)
    assert again.requisition_id == result.requisition_id
    assert replenishment.refresh(world["tenant"]) == 0  # pending 15 prevents duplicate demand.
    with pytest.raises(ValidationError, match="own|independent|requester|approve"):
        ProcurementService.approve_requisition(requisition=result.requisition, approver=world["operator"])
    policy.refresh_from_db()
    assert policy.target_stock == 20


def test_warehouse_completion_requires_underlying_document_and_tenant_assignment(world, received_stock):  # noqa: F811
    from django.core.exceptions import ValidationError

    from apps.inventory import warehouse

    receipt, _, _ = received_stock
    item = warehouse.create(tenant=world["tenant"], actor=world["operator"], task_type="RECEIVE", source_id=receipt.pk)
    warehouse.transition(item=item, actor=world["operator"], action="assign", assignee=world["operator"])
    warehouse.transition(item=item, actor=world["operator"], action="start")
    result = warehouse.transition(
        item=item, actor=world["operator"], action="complete", evidence="Physical quarantine receipt verified"
    )
    assert result.status == "COMPLETED"
    with pytest.raises(ValidationError, match="Terminal"):
        warehouse.transition(item=item, actor=world["operator"], action="cancel", evidence="Too late")
    task = warehouse.create(
        tenant=world["tenant"], actor=world["operator"], task_type="PUTAWAY", source_id=received_stock[1].pk
    )
    warehouse.transition(item=task, actor=world["operator"], action="assign", assignee=world["operator"])
    warehouse.transition(item=task, actor=world["operator"], action="start")
    with pytest.raises(ValidationError, match="authoritative"):
        warehouse.transition(
            item=task, actor=world["operator"], action="complete", evidence="Unreleased goods cannot be put away"
        )


def test_discard_preserves_source_and_demands_fresh_acquisition_evidence(world):  # noqa: F811
    from tests.test_hq_queue_completion import opening

    from apps.medicines.onboarding import missing_details
    from apps.medicines.onboarding_discard import discard_import
    from apps.medicines.onboarding_models import LegacyCatalogueItem

    item, _, _ = opening(world)
    del item.review["confirmed_cost"]
    assert "Verified acquisition cost per selling unit" in missing_details(item)
    args = dict(
        batch=item.import_batch, actor=world["operator"], reason="Unverified source discarded", expected_items=1
    )
    assert discard_import(**args)["discarded"] == 1
    assert discard_import(**args)["discarded"] == 0
    assert LegacyCatalogueItem.all_objects.get(pk=item.pk).source_quantity == 999
    response = world["client"].get("/api/medicines/initial-setup/")
    assert response.status_code == 200 and response.data["count"] == 0


def test_nonexpiring_supply_scan_converts_units_and_waits_for_quality(world, received_stock):  # noqa: F811
    from apps.inventory.models import BarcodeMaster
    from apps.medicines.models import CommercialSKU
    from apps.procurement.models import PurchaseOrderLine, ReceivedBatch
    from apps.procurement.services.receiving_service import GoodsReceivingService, ReceivingService

    receipt, _, quarantine = received_stock
    receipt.purchase_order.status = "SENT"
    receipt.purchase_order.save()
    sku = CommercialSKU.all_objects.create(
        tenant=world["tenant"],
        sku_code="NONEXP-SUP",
        display_name="Gauze synthetic fixture",
        package_definition=world["sku"].package_definition,
        product_kind="SUPPLY",
        manufactured_product=None,
        batch_tracking_required=False,
        expiry_tracking_required=False,
        stock_tracking_required=True,
        is_dispensable=False,
        status="ACTIVE",
    )
    BarcodeMaster.all_objects.create(tenant=world["tenant"], sku=sku, barcode="CASE-5", pack_conversion=5)
    PurchaseOrderLine.all_objects.create(
        tenant=world["tenant"],
        purchase_order=receipt.purchase_order,
        sku=sku,
        ordered_quantity=10,
        unit_price=2,
        total_price=20,
    )
    session = ReceivingService.open_receiving_session(
        tenant=world["tenant"],
        purchase_order=receipt.purchase_order,
        branch=world["branch"],
        delivery_note_number="SUPPLY-DELIVERY",
        received_by=world["operator"],
    )
    scan = ReceivingService.record_scan(
        session=session,
        sku=sku,
        scanned_barcode="CASE-5",
        batch_number="INTERNAL-SUPPLY-LOT",
        expiry_date=None,
        scanned_quantity=2,
    )
    assert scan.scanned_quantity == 10 and Decimal(scan.unit_evidence["pack_conversion"]) == 5
    result = ReceivingService.post_goods_receipt_note(
        session=session, destination_location=quarantine, actor=world["operator"]
    )
    batch = ReceivedBatch.all_objects.get(grn_line__goods_receipt=result)
    assert batch.expiry_date is None and batch.accepted_quantity == 0
    stock = InventoryBalance.all_objects.get(sku=sku)
    assert stock.on_hand == 10 and stock.available == 0
    assert stock.inventory_batch.lot_kind == "INTERNAL"
    with pytest.raises(ValidationError, match="expiry"):
        GoodsReceivingService.capture_batch(
            grn_line=received_stock[1].grn_line,
            manufacturer_batch_number="BAD-RX",
            expiry_date=None,
            received_quantity=1,
        )


def test_receiving_retry_does_not_double_book_or_accept_changed_quantity(world, received_stock):  # noqa: F811
    from apps.procurement.services.receiving_service import GoodsReceivingService

    receipt, _, _ = received_stock
    line = received_stock[1].grn_line.po_line
    line.ordered_quantity = 10
    line.save()
    args = dict(
        goods_receipt=receipt,
        po_line=line,
        manufacturer_batch_number="SECOND-LOT",
        expiry_date=timezone.localdate() + timezone.timedelta(days=100),
        received_quantity=5,
        idempotency_key="SECOND-5",
    )
    first = GoodsReceivingService.receive_batch(**args)
    second = GoodsReceivingService.receive_batch(**args)
    assert second.pk == first.pk
    line.refresh_from_db()
    assert line.received_quantity == 10
    with pytest.raises(ValidationError, match="different delivery"):
        GoodsReceivingService.receive_batch(**{**args, "received_quantity": 4})


def test_planning_api_has_tenant_scope_and_no_generic_status_mutation(world, received_stock):  # noqa: F811
    from rest_framework.test import APIClient

    from apps.identity.models import User
    from apps.tenancy.models import Tenant

    response = world["client"].post(
        "/api/inventory/replenishment-policies/",
        {
            "branch": str(world["branch"].pk),
            "sku": str(world["sku"].pk),
            "destination": str(world["store"].pk),
            "safety_stock": "1",
            "reorder_point": "8",
            "target_stock": "20",
            "order_multiple": 1,
            "lead_days": 2,
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert (
        world["client"]
        .patch(
            "/api/inventory/replenishment-policies/" + response.data["id"] + "/", {"target_stock": "999"}, format="json"
        )
        .status_code
        == 405
    )
    other = Tenant.objects.create(name="Other planning tenant", slug="other-plan")
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="other-planner", tenant=other, is_superuser=True))
    assert client.get("/api/inventory/replenishment-policies/").data == []
    client.force_authenticate(User.objects.create_user(username="no-planning-rights", tenant=world["tenant"]))
    assert client.post("/api/inventory/replenishment/refresh/", {}, format="json").status_code == 403


def test_rejected_return_is_not_subtracted_twice_from_release_allowance(world, received_stock):
    from apps.procurement.services.receiving_service import GoodsReceivingService

    receipt, batch, location = received_stock
    batch.rejected_quantity, batch.quarantined_quantity = 2, 3
    batch.save()
    line = batch.grn_line
    line.rejected_quantity, line.quarantined_quantity = 2, 3
    line.save()
    other = reviewer(world)
    qualify(receipt, other)
    item = SupplierReturnService.request_return(
        tenant=world["tenant"],
        return_number="REJECTED-RETURN",
        goods_receipt=receipt,
        reason="Two rejected units",
        requested_by=world["operator"],
        expected_credit=40,
    )
    SupplierReturnService.add_return_line(
        supplier_return=item, sku=world["sku"], quantity=2, batch=batch, source_location=location
    )
    SupplierReturnService.approve(supplier_return=item, approver=other)
    SupplierReturnService.dispatch(supplier_return=item, actor=world["operator"])
    BatchQualityDecisionService.record_decision(
        batch=batch,
        inspector=other,
        decision_by=other,
        outcome="APPROVE_FOR_RELEASE",
        reason="Three remaining packs passed inspection",
    )
    updated = GoodsReceivingService.release_batch(
        batch=batch, actor=other, quantity=3, reason="Independent inspection completed"
    )
    assert updated.accepted_quantity == 3 and updated.quarantined_quantity == 0


def test_reservation_refuses_date_only_deadlines_and_retries_after_deadline(world, monkeypatch):
    from datetime import date


    args = dict(
        tenant=world["tenant"],
        branch=world["branch"],
        source_location=world["store"],
        sku=world["sku"],
        requested_quantity=Decimal(2),
        purpose="DEADLINE",
        actor=world["operator"],
        idempotency_key="deadline-key",
    )
    with pytest.raises(ValidationError, match="aware date and time"):
        InventoryReservationService.reserve_stock(**args, expiry_time=date.today())
    deadline = timezone.now() + timezone.timedelta(hours=1)
    first = InventoryReservationService.reserve_stock(**args, expiry_time=deadline)
    monkeypatch.setattr(timezone, "now", lambda: deadline + timezone.timedelta(hours=1))
    again = InventoryReservationService.reserve_stock(**args, expiry_time=deadline)
    assert again.pk == first.pk
