from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventory.models import BarcodeMaster, InventoryBalance, InventoryBatch, InventoryLocation
from apps.medicines.models import (
    BranchAssortment,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pos_shift.models import BusinessDay, OperatorShift, PosRegister, RegisterSession
from apps.pos_transactions.models import PosTransaction, PosTransactionLine
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion
from apps.tenancy.models import Tenant
from apps.identity.models import User


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
        status=ClinicalMedicinalProduct.STATUS_ACTIVE,
    )
    manufactured = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant,
        code="POS-MP",
        brand_name="Retail product",
        clinical_product=clinical,
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
    InventoryBalance.all_objects.create(
        tenant=tenant,
        branch=branch,
        location=store,
        sku=sku,
        inventory_batch=None,
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


def test_retail_draft_is_bound_to_authoritative_register_context(world):
    draft = create_draft(world)

    assert draft["register"] == str(world["register"].pk)
    assert draft["register_session"] == str(world["session"].pk)
    assert draft["operator_shift"] == str(world["operator_shift"].pk)
    assert draft["business_day"] == str(world["business_day"].pk)
    assert draft["state"] == "DRAFT"


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
