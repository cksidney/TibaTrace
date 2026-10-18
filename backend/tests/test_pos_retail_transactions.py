from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.inventory.models import (
    BarcodeMaster,
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
)
from apps.medicines.models import (
    BranchAssortment,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pos_shift.cash_control import CashControlService
from apps.pos_shift.models import BusinessDay, OperatorShift, PosRegister, RegisterSession
from apps.pos_transactions.models import PosTransaction, PosTransactionLine, RetailCashReceipt
from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Retail POS Tenant", slug="retail-pos")
    organization = Organization.all_objects.create(tenant=tenant, code="POS-ORG", name="Retail Pharmacy")
    branch = Location.all_objects.create(tenant=tenant, organization=organization, code="POS-ELD", name="Eldoret")
    operator = User.objects.create_user(
        username="retail-cashier", password="pw", tenant=tenant, is_superuser=True
    )
    register = PosRegister.all_objects.create(
        tenant=tenant,
        location=branch,
        code="RETAIL-01",
        name="Retail till",
        device_id="POS-RETAIL-01",
        state="OPEN",
    )
    business_day = BusinessDay.all_objects.create(
        tenant=tenant, location=branch, business_date=timezone.localdate(), state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=business_day, opened_by=operator, state="OPEN"
    )
    operator_shift = OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )
    store = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=branch,
        location_code="RETAIL",
        name="Retail store",
        location_type=InventoryLocation.LocationType.STORE,
    )
    dose_form = DoseForm.objects.create(code="POS-TAB", name="Tablet")
    clinical = ClinicalMedicinalProduct.objects.create(
        tenant=tenant,
        code="POS-CMP",
        canonical_name="Retail product",
        dose_form=dose_form,
        prescription_classification="OTC",
        status=ClinicalMedicinalProduct.STATUS_ACTIVE,
    )
    manufacturer = Manufacturer.all_objects.create(
        tenant=tenant,
        code="POS-MFR",
        legal_name="Retail Product Manufacturer",
    )
    manufactured = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant,
        code="POS-MP",
        brand_name="Retail product",
        clinical_product=clinical,
        manufacturer=manufacturer,
        status=ManufacturedMedicinalProduct.STATUS_ACTIVE,
    )
    package = PackageDefinition.objects.create(
        code="POS-PACK", description="Retail pack", unit_of_measure="pack"
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="POS-001",
        display_name="Retail product 500mg",
        manufactured_product=manufactured,
        package_definition=package,
        default_barcode="618000001",
        status=CommercialSKU.STATUS_ACTIVE,
    )
    BranchAssortment.all_objects.create(tenant=tenant, location=branch, sku=sku, is_sellable=True)
    price_book = PriceBook.all_objects.create(
        tenant=tenant,
        code="POS-RETAIL",
        name="POS retail",
        scope_type=PriceBook.ScopeType.TENANT,
        price_type=PriceBook.PriceType.RETAIL,
    )
    version = PriceBookVersion.all_objects.create(
        tenant=tenant,
        price_book=price_book,
        version_number=1,
        status=PriceBookVersion.Status.ACTIVE,
        effective_from=timezone.localdate() - timedelta(days=1),
    )
    PriceBookEntry.all_objects.create(
        tenant=tenant, version=version, sku=sku, unit_price=Decimal("125.00")
    )
    PriceAssignment.all_objects.create(
        tenant=tenant, price_book=price_book, scope_type=PriceBook.ScopeType.TENANT
    )
    retail_batch = InventoryBatch.all_objects.create(
        tenant=tenant,
        sku=sku,
        manufactured_product=manufactured,
        manufacturer_batch_number="RETAIL-AVAILABLE-1",
        expiry_date=timezone.localdate() + timedelta(days=120),
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        recall_status=InventoryBatch.RecallStatus.NONE,
    )
    InventoryBalance.all_objects.create(
        tenant=tenant,
        branch=branch,
        location=store,
        sku=sku,
        inventory_batch=retail_batch,
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        expiry_status="NORMAL",
        on_hand=Decimal("8.0000"),
        available=Decimal("8.0000"),
    )
    BarcodeMaster.all_objects.create(tenant=tenant, sku=sku, barcode="618000001")
    client = APIClient()
    client.force_authenticate(user=operator)
    return {
        "tenant": tenant,
        "branch": branch,
        "store": store,
        "operator": operator,
        "register": register,
        "business_day": business_day,
        "session": session,
        "operator_shift": operator_shift,
        "sku": sku,
        "client": client,
    }


def create_draft(world):
    response = world["client"].post(
        "/api/pos/retail/transactions/draft/",
        {"device_id": "POS-RETAIL-01", "store_id": str(world["store"].pk)},
        format="json",
    )
    assert response.status_code == 201
    return response.json()


def prepare_sale_for_payment(world, quantity="2.0000"):
    draft = create_draft(world)
    line = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {
            "device_id": "POS-RETAIL-01",
            "sku_id": str(world["sku"].pk),
            "quantity": quantity,
        },
        format="json",
    )
    assert line.status_code == 201
    prepared = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/ready-for-payment/",
        {"device_id": "POS-RETAIL-01"},
        format="json",
    )
    assert prepared.status_code == 200
    return prepared.json()


def test_retail_draft_is_bound_to_authoritative_register_context(world):
    draft = create_draft(world)

    assert draft["register"] == str(world["register"].pk)
    assert draft["register_session"] == str(world["session"].pk)
    assert draft["operator_shift"] == str(world["operator_shift"].pk)
    assert draft["business_day"] == str(world["business_day"].pk)
    assert draft["state"] == "DRAFT"


def test_retail_draft_rejects_active_but_non_sellable_inventory_location(world):
    receiving = InventoryLocation.all_objects.create(
        tenant=world["tenant"],
        branch=world["branch"],
        location_code="RETAIL-RECEIVING",
        name="Receiving bay",
        location_type=InventoryLocation.LocationType.RECEIVING,
        status=InventoryLocation.Status.ACTIVE,
    )

    response = world["client"].post(
        "/api/pos/retail/transactions/draft/",
        {"device_id": "POS-RETAIL-01", "store_id": str(receiving.pk)},
        format="json",
    )

    assert response.status_code == 400
    assert "sellable store" in str(response.json()).lower()
    assert not PosTransaction.all_objects.filter(store=receiving).exists()


def test_retail_basket_rechecks_store_type_after_draft_creation(world):
    draft = create_draft(world)
    world["store"].location_type = InventoryLocation.LocationType.RECEIVING
    world["store"].save(update_fields=["location_type", "updated_at"])

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {"device_id": "POS-RETAIL-01", "sku_id": str(world["sku"].pk), "quantity": "1"},
        format="json",
    )

    assert response.status_code == 400
    assert "sellable store" in str(response.json()).lower()
    assert not PosTransactionLine.all_objects.filter(transaction_id=draft["id"]).exists()


def test_barcode_scan_adds_then_increments_authoritative_line(world):
    draft = create_draft(world)
    payload = {"device_id": "POS-RETAIL-01", "barcode": "618000001", "quantity": "2.0000"}

    first = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/scan/", payload, format="json"
    )
    second = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/scan/", payload, format="json"
    )

    assert first.status_code == 201
    assert second.status_code == 201
    line = PosTransactionLine.all_objects.get(transaction_id=draft["id"])
    assert line.quantity == Decimal("4.0000")
    assert line.line_total == Decimal("500.00")
    assert line.scan_source == "BARCODE"
    assert line.inventory_context.stock_state == "IN_STOCK"
    transaction_record = PosTransaction.all_objects.get(pk=draft["id"])
    assert transaction_record.total == Decimal("500.00")


def test_catalogue_hides_items_without_an_authoritative_price(world):
    PriceBookEntry.all_objects.filter(tenant=world["tenant"], sku=world["sku"]).delete()

    response = world["client"].post(
        "/api/pos/retail/catalogue/search/",
        {
            "device_id": "POS-RETAIL-01",
            "store_id": str(world["store"].pk),
            "query": "Retail product",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == []


def test_retail_checkout_blocks_prescription_and_controlled_products(world):
    clinical = world["sku"].manufactured_product.clinical_product
    clinical.prescription_classification = "PRESCRIPTION_ONLY"
    clinical.save(update_fields=["prescription_classification", "updated_at"])
    draft = create_draft(world)

    search = world["client"].post(
        "/api/pos/retail/catalogue/search/",
        {
            "device_id": "POS-RETAIL-01",
            "store_id": str(world["store"].pk),
            "query": "Retail product",
        },
        format="json",
    )
    add_line = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {"device_id": "POS-RETAIL-01", "sku_id": str(world["sku"].pk), "quantity": "1"},
        format="json",
    )

    assert search.status_code == 200 and search.json() == []
    assert add_line.status_code == 400
    assert "clinical" in str(add_line.json()).lower()
    assert not PosTransactionLine.all_objects.filter(transaction_id=draft["id"]).exists()

    clinical.prescription_classification = "OTC"
    clinical.controlled_classification = "CONTROLLED"
    clinical.save(update_fields=["prescription_classification", "controlled_classification", "updated_at"])
    controlled_add = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {"device_id": "POS-RETAIL-01", "sku_id": str(world["sku"].pk), "quantity": "1"},
        format="json",
    )
    assert controlled_add.status_code == 400
    assert "controlled" in str(controlled_add.json()).lower()


def test_retail_checkout_rechecks_catalogue_fitness_at_sale_time(world):
    world["sku"].manufactured_product.manufacturer.is_active = False
    world["sku"].manufactured_product.manufacturer.save(update_fields=["is_active", "updated_at"])
    draft = create_draft(world)

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {"device_id": "POS-RETAIL-01", "sku_id": str(world["sku"].pk), "quantity": "1"},
        format="json",
    )

    assert response.status_code == 400
    assert "manufacturer" in str(response.json()).lower()
    assert not PosTransactionLine.all_objects.filter(transaction_id=draft["id"]).exists()


def test_catalogue_never_counts_expired_batch_stock_as_sellable(world):
    InventoryBalance.all_objects.filter(tenant=world["tenant"], sku=world["sku"]).update(
        on_hand=Decimal("0.0000"), available=Decimal("0.0000")
    )
    expired_batch = InventoryBatch.all_objects.create(
        tenant=world["tenant"],
        sku=world["sku"],
        manufactured_product=world["sku"].manufactured_product,
        manufacturer_batch_number="EXPIRED-RETAIL-1",
        expiry_date=timezone.localdate() - timedelta(days=1),
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        recall_status=InventoryBatch.RecallStatus.NONE,
    )
    InventoryBalance.all_objects.create(
        tenant=world["tenant"],
        branch=world["branch"],
        location=world["store"],
        sku=world["sku"],
        inventory_batch=expired_batch,
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        expiry_status="NORMAL",
        on_hand=Decimal("8.0000"),
        available=Decimal("8.0000"),
    )

    response = world["client"].post(
        "/api/pos/retail/catalogue/search/",
        {
            "device_id": "POS-RETAIL-01",
            "store_id": str(world["store"].pk),
            "query": "Retail product",
        },
        format="json",
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["available_quantity"] == "0.0000"
    assert response.json()[0]["stock_state"] == "OUT_OF_STOCK"

    draft = create_draft(world)
    add_line = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {
            "device_id": "POS-RETAIL-01",
            "sku_id": str(world["sku"].pk),
            "quantity": "1.0000",
        },
        format="json",
    )

    assert add_line.status_code == 400
    assert "insufficient eligible stock" in str(add_line.json()).lower()


def test_retail_activity_is_rejected_when_operator_shift_closes(world):
    draft = create_draft(world)
    world["operator_shift"].state = "CLOSED"
    world["operator_shift"].save(update_fields=["state", "updated_at"])

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/add-line/",
        {
            "device_id": "POS-RETAIL-01",
            "sku_id": str(world["sku"].pk),
            "quantity": "1.0000",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "active shift" in str(response.json()).lower()


def test_paid_transaction_context_cannot_be_changed(world):
    draft = create_draft(world)
    transaction_record = PosTransaction.all_objects.get(pk=draft["id"])
    transaction_record.state = PosTransaction.State.PAYMENT_IN_PROGRESS
    transaction_record.save(update_fields=["state", "updated_at"])
    transaction_record.device_id = "OTHER-DEVICE"

    with pytest.raises(ValidationError, match="cannot move"):
        transaction_record.save(update_fields=["device_id", "updated_at"])


def test_cash_settlement_issues_fefo_stock_and_reconciles_net_sale_value(world):
    draft = prepare_sale_for_payment(world)

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "300.00",
            "idempotency_key": f"retail-{draft['id']}",
            "tender_type": "CASH",
        },
        format="json",
    )

    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "COMPLETED"
    assert result["receipt"]["tender_type"] == "CASH"
    assert result["receipt"]["amount"] == "250.00"
    assert result["receipt"]["cash_received"] == "300.00"
    assert result["receipt"]["change_due"] == "50.00"
    assert "not a fiscal/eTIMS receipt" in result["receipt"]["disclaimer"]
    assert len(result["receipt"]["lines_snapshot"]) == 1
    assert result["receipt"]["print_job"]["status"] == PosPrintJob.Status.QUEUED
    document = PosPrintDocument.all_objects.get(document_number=result["receipt"]["receipt_number"])
    assert document.document_type == PosPrintDocument.DocumentType.RETAIL_RECEIPT
    assert document.snapshot["payment"]["cash_received"] == "300.00"
    cash_receipt = RetailCashReceipt.all_objects.get(transaction_id=draft["id"])
    with pytest.raises(ValidationError, match="immutable"):
        cash_receipt.save()
    with pytest.raises(ValidationError, match="immutable"):
        RetailCashReceipt.all_objects.filter(pk=cash_receipt.pk).update(amount=Decimal("1.00"))
    with pytest.raises(ValidationError, match="immutable"):
        RetailCashReceipt.all_objects.filter(pk=cash_receipt.pk).delete()
    completed_transaction = PosTransaction.all_objects.get(pk=draft["id"])
    completed_transaction.total = Decimal("1.00")
    with pytest.raises(ValidationError, match="total is immutable"):
        completed_transaction.save(update_fields=["total", "updated_at"])
    completed_transaction.refresh_from_db()
    completed_transaction.state = PosTransaction.State.READY_FOR_PAYMENT
    with pytest.raises(ValidationError, match="cannot be reopened"):
        completed_transaction.save(update_fields=["state", "updated_at"])
    completed_line = PosTransactionLine.all_objects.get(transaction_id=draft["id"])
    completed_line.quantity = Decimal("3.0000")
    with pytest.raises(ValidationError, match="Only draft or held"):
        completed_line.save(update_fields=["quantity", "updated_at"])
    with pytest.raises(ValidationError, match="Only draft or held"):
        PosTransactionLine.all_objects.filter(pk=completed_line.pk).update(quantity=Decimal("3.0000"))
    with pytest.raises(ValidationError, match="Only draft or held"):
        completed_line.delete()

    issue = InventoryLedgerEntry.all_objects.get(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION", source_document_id=draft["id"]
    )
    assert issue.entry_type == InventoryLedgerEntry.EntryType.ISSUE
    assert issue.quantity_delta == Decimal("-2.0000")
    assert issue.base_quantity_delta == Decimal("-2.0000")
    assert issue.inventory_batch.manufacturer_batch_number == "RETAIL-AVAILABLE-1"
    assert CashControlService.tender_breakdown(session=world["session"]).cash == Decimal("250.00")
    assert CashControlService.expected_cash(session=world["session"]).expected == Decimal("250.00")


def test_cash_settlement_issues_batches_in_first_expiry_first_out_order(world):
    earlier_batch = InventoryBatch.all_objects.create(
        tenant=world["tenant"],
        sku=world["sku"],
        manufactured_product=world["sku"].manufactured_product,
        manufacturer_batch_number="RETAIL-FEFO-EARLIER",
        expiry_date=timezone.localdate() + timedelta(days=60),
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        recall_status=InventoryBatch.RecallStatus.NONE,
    )
    InventoryBalance.all_objects.create(
        tenant=world["tenant"],
        branch=world["branch"],
        location=world["store"],
        sku=world["sku"],
        inventory_batch=earlier_batch,
        quality_status=InventoryBatch.QualityStatus.RELEASED,
        expiry_status="NORMAL",
        on_hand=Decimal("1.0000"),
        available=Decimal("1.0000"),
    )
    draft = prepare_sale_for_payment(world, quantity="1.0000")

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "125.00",
            "idempotency_key": f"retail-{draft['id']}",
        },
        format="json",
    )

    assert response.status_code == 200
    issued_batch_numbers = list(
        InventoryLedgerEntry.all_objects.filter(
            tenant=world["tenant"], source_document_id=draft["id"]
        ).order_by("transaction_timestamp").values_list("inventory_batch__manufacturer_batch_number", flat=True)
    )
    assert issued_batch_numbers == ["RETAIL-FEFO-EARLIER"]


def test_cash_settlement_replay_is_idempotent_and_does_not_issue_stock_twice(world):
    draft = prepare_sale_for_payment(world)
    payload = {
        "device_id": "POS-RETAIL-01",
        "cash_received": "250.00",
        "idempotency_key": f"retail-{draft['id']}",
    }

    first = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/", payload, format="json"
    )
    replay = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/", payload, format="json"
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["receipt"]["receipt_number"] == replay.json()["receipt"]["receipt_number"]
    assert InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION", source_document_id=draft["id"]
    ).count() == 1
    conflict = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {**payload, "cash_received": "300.00"},
        format="json",
    )
    assert conflict.status_code == 400


def test_cash_settlement_rejects_short_cash_without_touching_stock(world):
    draft = prepare_sale_for_payment(world)
    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "249.99",
            "idempotency_key": f"retail-{draft['id']}",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "less than the sale total" in str(response.json()).lower()
    assert PosTransaction.all_objects.get(pk=draft["id"]).state == PosTransaction.State.READY_FOR_PAYMENT
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()


def test_ready_for_payment_sale_can_be_cancelled_without_settlement(world):
    draft = prepare_sale_for_payment(world)
    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cancel/",
        {
            "device_id": "POS-RETAIL-01",
            "reason": "Customer left before tender.",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["state"] == "CANCELLED"
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()


def test_retail_cash_endpoint_rejects_card_and_mpesa_tenders(world):
    draft = prepare_sale_for_payment(world)

    for tender_type in ("CARD", "MPESA"):
        response = world["client"].post(
            f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
            {
                "device_id": "POS-RETAIL-01",
                "cash_received": "250.00",
                "idempotency_key": f"{tender_type.lower()}-{draft['id']}",
                "tender_type": tender_type,
            },
            format="json",
        )
        assert response.status_code == 400

    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()


def test_cash_settlement_requires_the_cash_accept_capability(world):
    draft = prepare_sale_for_payment(world)
    cashier_without_payment_rights = User.objects.create_user(
        username="retail-read-only", password="pw", tenant=world["tenant"]
    )
    client = APIClient()
    client.force_authenticate(user=cashier_without_payment_rights)

    response = client.post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "250.00",
            "idempotency_key": f"retail-{draft['id']}",
        },
        format="json",
    )

    assert response.status_code == 403
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()


def test_settlement_reprices_and_returns_to_draft_before_accepting_cash(world):
    draft = prepare_sale_for_payment(world)
    PriceBookEntry.all_objects.filter(tenant=world["tenant"], sku=world["sku"]).update(
        unit_price=Decimal("130.00")
    )

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "300.00",
            "idempotency_key": f"retail-{draft['id']}",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["state"] == "DRAFT"
    assert response.json()["total"] == "260.00"
    assert response.json()["receipt"] is None
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()


def test_settlement_reopens_basket_if_eligible_stock_disappears(world):
    draft = prepare_sale_for_payment(world)
    InventoryBalance.all_objects.filter(tenant=world["tenant"], sku=world["sku"]).update(
        on_hand=Decimal("0.0000"), available=Decimal("0.0000")
    )

    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/cash-settle/",
        {
            "device_id": "POS-RETAIL-01",
            "cash_received": "300.00",
            "idempotency_key": f"retail-{draft['id']}",
        },
        format="json",
        HTTP_X_TENANT_ID=str(world["tenant"].pk),
    )

    assert response.status_code == 200
    assert response.json()["state"] == "DRAFT"
    assert response.json()["lines"][0]["inventory_context"]["stock_state"] == "OUT_OF_STOCK"
    assert response.json()["receipt"] is None
    assert not InventoryLedgerEntry.all_objects.filter(
        tenant=world["tenant"], source_document_type="POS_RETAIL_TRANSACTION"
    ).exists()
