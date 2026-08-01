from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLocation,
    StockTransfer,
    StockTransferLine,
)
from apps.inventory.services import InventoryLedgerService, StockTransferService
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.tenancy.models import Tenant

PASSWORD = "stock-transfer-test-password"


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def transfer_world(db):
    tenant = Tenant.objects.create(
        name="Transfer Pharmacy",
        slug="transfer-pharmacy",
        status=Tenant.STATUS_ACTIVE,
    )
    organization = Organization.all_objects.create(
        tenant=tenant,
        code="TRANSFER-ORG",
        name="Transfer Pharmacy",
    )
    source_branch = Location.all_objects.create(
        tenant=tenant,
        organization=organization,
        code="SOURCE",
        name="Source Branch",
        location_type="BRANCH",
    )
    destination_branch = Location.all_objects.create(
        tenant=tenant,
        organization=organization,
        code="DESTINATION",
        name="Destination Branch",
        location_type="BRANCH",
    )
    source_location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=source_branch,
        location_code="SOURCE-STORE",
        name="Source Store",
        location_type=InventoryLocation.LocationType.STORE,
    )
    destination_location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=destination_branch,
        location_code="DESTINATION-STORE",
        name="Destination Store",
        location_type=InventoryLocation.LocationType.STORE,
    )
    InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=destination_branch,
        location_code="DESTINATION-DAMAGED",
        name="Damaged Goods",
        location_type=InventoryLocation.LocationType.DAMAGED,
        damaged_goods_capability=True,
    )
    dose_form = DoseForm.objects.create(code="TRANSFER-TAB", name="Tablet")
    package = PackageDefinition.objects.create(
        code="TRANSFER-PACK",
        description="Transfer pack",
        unit_of_measure="pack",
    )
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="TRANSFER-CMP",
        canonical_name="Transfer Medicine",
        dose_form=dose_form,
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="TRANSFER-MP",
        brand_name="Transfer Brand",
        clinical_product=clinical,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="TRANSFER-SKU",
        default_barcode="6161100012345",
        display_name="Transfer Brand 10s",
        manufactured_product=manufactured,
        package_definition=package,
        status=CommercialSKU.STATUS_ACTIVE,
    )
    batch = InventoryBatch.all_objects.create(
        tenant=tenant,
        sku=sku,
        manufactured_product=manufactured,
        manufacturer_batch_number="TRANSFER-BATCH",
        expiry_date=date.today() + timedelta(days=365),
    )
    requester = User.objects.create_user(
        username="transfer-requester",
        password=PASSWORD,
        tenant=tenant,
    )
    approver = User.objects.create_user(
        username="transfer-approver",
        password=PASSWORD,
        tenant=tenant,
    )
    receiver = User.objects.create_user(
        username="transfer-receiver",
        password=PASSWORD,
        tenant=tenant,
    )
    InventoryLedgerService.post_entry(
        tenant=tenant,
        branch=source_branch,
        location=source_location,
        sku=sku,
        inventory_batch=batch,
        entry_type="RECEIPT",
        quantity_delta=Decimal("10"),
        unit="pack",
        base_quantity_delta=Decimal("10"),
        effective_timestamp=timezone.now(),
        source_document_type="OPENING_BALANCE",
        source_document_id="opening-transfer-stock",
        idempotency_key="opening-transfer-stock",
        actor=requester,
    )
    return {
        "tenant": tenant,
        "source_location": source_location,
        "destination_location": destination_location,
        "sku": sku,
        "batch": batch,
        "requester": requester,
        "approver": approver,
        "receiver": receiver,
    }


def authenticated_client(user):
    client = APIClient()
    response = client.post(
        "/api/identity/session/",
        {"username": user.username, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200, response.content
    return client


@pytest.mark.django_db
def test_stock_transfer_api_enforces_governed_lifecycle(transfer_world):
    tenant_header = {"HTTP_X_TENANT_ID": str(transfer_world["tenant"].pk)}
    requester_client = authenticated_client(transfer_world["requester"])
    create_response = requester_client.post(
        "/api/inventory/transfers/",
        {
            "transfer_number": "TRF-API-001",
            "source_location": str(transfer_world["source_location"].pk),
            "destination_location": str(transfer_world["destination_location"].pk),
            "reason": "Rebalance branch stock",
            "document_reference": "REQ-001",
            "lines": [
                {
                    "sku": str(transfer_world["sku"].pk),
                    "quantity": "4.0000",
                }
            ],
        },
        format="json",
        **tenant_header,
    )
    assert create_response.status_code == 201, create_response.content
    transfer_id = create_response.json()["id"]
    line_id = create_response.json()["lines"][0]["id"]
    assert create_response.json()["status"] == StockTransfer.Status.SUBMITTED
    assert create_response.json()["lines"][0]["sku_barcode"] == "6161100012345"

    balances = rows(requester_client.get("/api/inventory/balances/", **tenant_header))
    assert balances[0]["sku_barcode"] == "6161100012345"

    self_approval = requester_client.post(
        f"/api/inventory/transfers/{transfer_id}/approve/",
        {},
        format="json",
        **tenant_header,
    )
    assert self_approval.status_code == 400
    assert "cannot approve" in str(self_approval.json()).lower()

    approver_client = authenticated_client(transfer_world["approver"])
    approval = approver_client.post(
        f"/api/inventory/transfers/{transfer_id}/approve/",
        {},
        format="json",
        **tenant_header,
    )
    assert approval.status_code == 200, approval.content
    assert approval.json()["status"] == StockTransfer.Status.APPROVED

    dispatch = approver_client.post(
        f"/api/inventory/transfers/{transfer_id}/dispatch/",
        {},
        format="json",
        **tenant_header,
    )
    assert dispatch.status_code == 200, dispatch.content
    assert dispatch.json()["status"] == StockTransfer.Status.DISPATCHED

    receiver_client = authenticated_client(transfer_world["receiver"])
    receipt_payload = {
        "idempotency_key": "receipt-api-001",
        "lines": [
            {
                "line_id": line_id,
                "batch_id": str(transfer_world["batch"].pk),
                "quantity": "4.0000",
                "damaged": "0.0000",
                "discrepancy_reason": "",
            }
        ],
    }
    receipt = receiver_client.post(
        f"/api/inventory/transfers/{transfer_id}/receive/",
        receipt_payload,
        format="json",
        **tenant_header,
    )
    assert receipt.status_code == 200, receipt.content
    assert receipt.json()["status"] == StockTransfer.Status.RECEIVED

    retry = receiver_client.post(
        f"/api/inventory/transfers/{transfer_id}/receive/",
        receipt_payload,
        format="json",
        **tenant_header,
    )
    assert retry.status_code == 200, retry.content

    source_balance = InventoryBalance.all_objects.get(
        tenant=transfer_world["tenant"],
        location=transfer_world["source_location"],
        sku=transfer_world["sku"],
        inventory_batch=transfer_world["batch"],
    )
    destination_balance = InventoryBalance.all_objects.get(
        tenant=transfer_world["tenant"],
        location=transfer_world["destination_location"],
        sku=transfer_world["sku"],
        inventory_batch=transfer_world["batch"],
    )
    assert source_balance.on_hand == Decimal("6")
    assert destination_balance.on_hand == Decimal("4")
    assert len(rows(receiver_client.get("/api/inventory/transfers/", **tenant_header))) == 1


@pytest.mark.django_db
def test_partial_and_damaged_transfer_receipts_preserve_custody(transfer_world):
    transfer = StockTransferService.request_transfer(
        tenant=transfer_world["tenant"],
        transfer_number="TRF-DAMAGE-001",
        source_branch=transfer_world["source_location"].branch,
        dest_branch=transfer_world["destination_location"].branch,
        source_location=transfer_world["source_location"],
        dest_location=transfer_world["destination_location"],
        requested_by=transfer_world["requester"],
        lines_data=[{"sku": transfer_world["sku"], "quantity": Decimal("4")}],
        reason="Rebalance with inspected receipt",
    )
    transfer = StockTransferService.approve_transfer(
        transfer=transfer,
        approver=transfer_world["approver"],
    )
    transfer = StockTransferService.allocate_and_dispatch(
        transfer=transfer,
        dispatcher=transfer_world["approver"],
    )
    line = StockTransferLine.all_objects.get(transfer=transfer)

    transfer = StockTransferService.receive_transfer(
        transfer=transfer,
        receiver=transfer_world["receiver"],
        idempotency_key="partial-receipt-001",
        received_lines_data=[
            {
                "line_id": line.pk,
                "batch_id": transfer_world["batch"].pk,
                "quantity": Decimal("3"),
                "damaged": Decimal("0"),
                "discrepancy_reason": "One pack held for damage inspection.",
            }
        ],
    )
    assert transfer.status == StockTransfer.Status.PARTIALLY_RECEIVED

    transfer = StockTransferService.receive_transfer(
        transfer=transfer,
        receiver=transfer_world["receiver"],
        idempotency_key="damage-receipt-001",
        received_lines_data=[
            {
                "line_id": line.pk,
                "batch_id": transfer_world["batch"].pk,
                "quantity": Decimal("0"),
                "damaged": Decimal("1"),
                "discrepancy_reason": "Outer pack crushed in transit.",
            }
        ],
    )
    assert transfer.status == StockTransfer.Status.RECEIVED
    line.refresh_from_db()
    assert line.received_quantity == Decimal("3")
    assert line.damaged_quantity == Decimal("1")
    damaged_balance = InventoryBalance.all_objects.get(
        tenant=transfer_world["tenant"],
        location__damaged_goods_capability=True,
        sku=transfer_world["sku"],
        inventory_batch=transfer_world["batch"],
    )
    assert damaged_balance.on_hand == Decimal("1")
    assert damaged_balance.available == Decimal("0")
