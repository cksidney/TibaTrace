"""Comprehensive test suite for KRA eTIMS VSCU API and Fiscalization Pipeline."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.inventory.models import InventoryLocation
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
from apps.pos_transactions.models import PosTransaction, PosTransactionLine, RetailCashReceipt
from apps.pos_transactions.services import PosRetailService
from apps.prescription.fiscal_models import FiscalSubmission
from apps.taxation.models import FiscalReceipt, TenantEtimsProfile
from apps.taxation.qr_generator import (
    build_kra_qr_verification_url,
    compute_offline_receipt_signature,
    construct_kra_qr_payload,
    generate_qr_data_uri,
    generate_qr_svg,
    get_kra_verify_base_url,
)
from apps.taxation.services import FiscalizationPipeline
from apps.taxation.vscu_client import VscuClient
from apps.tenancy.models import Tenant


@pytest.fixture
def test_setup(db):
    tenant = Tenant.objects.create(name="Apex Healthcare Ltd", slug="apex-health")
    organization = Organization.all_objects.create(tenant=tenant, code="APX-ORG", name="Apex Pharmacy")
    branch = Location.all_objects.create(tenant=tenant, organization=organization, code="APX-NRB", name="Apex Nairobi")
    operator = User.objects.create_user(
        username="cashier_jane", password="password123", tenant=tenant, is_superuser=True
    )
    register = PosRegister.all_objects.create(
        tenant=tenant,
        location=branch,
        code="REG-01",
        name="Till 1",
        currency="KES",
        device_id="DEV-01",
        state="OPEN",
    )
    business_day = BusinessDay.all_objects.create(
        tenant=tenant, location=branch, business_date=timezone.localdate(), state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=business_day, opened_by=operator, state="OPEN"
    )
    shift = OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )
    store = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=branch,
        location_code="MAIN-STORE",
        name="Main Dispensary",
        status=InventoryLocation.Status.ACTIVE,
    )

    dose_form = DoseForm.objects.create(code="TAB-01", name="Tablet")
    clinical = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-AMOX", canonical_name="Amoxicillin 500mg", dose_form=dose_form, status="ACTIVE"
    )
    mfg_exempt = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-AMOX", brand_name="Amoxil 500mg", clinical_product=clinical, status="ACTIVE"
    )
    package = PackageDefinition.objects.create(code="BX-1", description="Box", unit_of_measure="box")

    # SKU 1: Prescription Medicine (Exempt)
    sku_exempt = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="AMOX-500",
        display_name="Amoxil 500mg",
        manufactured_product=mfg_exempt,
        package_definition=package,
        default_barcode="618000001",
        tax_category="EXEMPT",
        is_saleable=True,
        status=CommercialSKU.STATUS_ACTIVE,
        stock_tracking_required=False,
    )
    BranchAssortment.all_objects.create(tenant=tenant, location=branch, sku=sku_exempt, is_sellable=True)

    # SKU 2: Cosmetic / General Good (Standard 16%)
    clinical_gen = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-BAND", canonical_name="Bandages", dose_form=dose_form, status="ACTIVE"
    )
    mfg_standard = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-BAND", brand_name="First Aid Bandages 10s", clinical_product=clinical_gen, status="ACTIVE"
    )
    sku_standard = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="BAND-AID-10",
        display_name="First Aid Bandages 10s",
        manufactured_product=mfg_standard,
        package_definition=package,
        default_barcode="618000002",
        tax_category="STANDARD",
        is_saleable=True,
        status=CommercialSKU.STATUS_ACTIVE,
        stock_tracking_required=False,
    )
    BranchAssortment.all_objects.create(tenant=tenant, location=branch, sku=sku_standard, is_sellable=True)

    # eTIMS Profile
    profile = TenantEtimsProfile.all_objects.create(
        tenant=tenant,
        is_enabled=True,
        environment=TenantEtimsProfile.Environment.SANDBOX,
        tin="P051234567Z",
        bhf_id="00",
        dvc_srl_no="VSCU-NRB-001",
        cm_key="TEST-AES-KEY-12345",
        sdc_id="SDC0010001",
        auto_fiscalize_pos_sales=True,
    )

    return {
        "tenant": tenant,
        "branch": branch,
        "store": store,
        "register": register,
        "user": operator,
        "bday": business_day,
        "shift": shift,
        "session": session,
        "sku_exempt": sku_exempt,
        "sku_standard": sku_standard,
        "profile": profile,
    }


# ==============================================================================
# 1. QR Code & Signature Tests
# ==============================================================================

def test_kra_qr_code_urls():
    sbx_url = get_kra_verify_base_url("SANDBOX")
    assert "etims-sbx.kra.go.ke" in sbx_url

    prod_url = get_kra_verify_base_url("PRODUCTION")
    assert "etims.kra.go.ke" in prod_url

    payload = construct_kra_qr_payload(
        tin="P051234567Z",
        bhf_id="00",
        sdc_id="SDC001",
        invoice_no=42,
        receipt_date_str="20261016140000",
        internal_data="INT12345",
        receipt_signature="SIG67890",
    )
    assert payload == "INT12345SIG67890"

    full_url = build_kra_qr_verification_url(payload=payload, environment="SANDBOX")
    assert "etims-sbx.kra.go.ke" in full_url
    assert "qrCode=INT12345SIG67890" in full_url


def test_qr_code_svg_and_data_uri_generation():
    url = "https://etims-sbx.kra.go.ke/common/link/etims/receipt/index.html?qrCode=TEST123"
    svg = generate_qr_svg(url)
    assert "<svg" in svg
    assert "</svg>" in svg

    data_uri = generate_qr_data_uri(svg)
    assert data_uri.startswith("data:image/svg+xml;base64,")


def test_deterministic_offline_signature():
    int_data, sig = compute_offline_receipt_signature(
        tin="P051234567Z",
        bhf_id="00",
        invoice_no=1,
        total_amount="1500.00",
        date_str="20261016120000",
        secret_key="my-secret-key",
    )
    assert len(int_data) == 16
    assert len(sig) == 16
    int_data2, sig2 = compute_offline_receipt_signature(
        tin="P051234567Z",
        bhf_id="00",
        invoice_no=1,
        total_amount="1500.00",
        date_str="20261016120000",
        secret_key="my-secret-key",
    )
    assert int_data == int_data2
    assert sig == sig2


# ==============================================================================
# 2. Tax Classification & Bucket Mapping
# ==============================================================================

def test_tax_category_mapping(test_setup):
    sku_exempt = test_setup["sku_exempt"]
    sku_standard = test_setup["sku_standard"]

    line_mock_exempt = MagicMock()
    line_mock_exempt.sku = sku_exempt
    line_mock_exempt.line_total = Decimal("1000.00")
    line_mock_exempt.quantity = Decimal("2")
    line_mock_exempt.unit_price = Decimal("500.00")
    line_mock_exempt.description_snapshot = "Amoxil 500mg"
    line_mock_exempt.unit = "BX"

    mapped_exempt = FiscalizationPipeline.map_line_tax(line_mock_exempt)
    assert mapped_exempt["tax_ty_cd"] == "E"
    assert mapped_exempt["taxable_amt"] == Decimal("1000.00")
    assert mapped_exempt["tax_amt"] == Decimal("0.00")

    line_mock_standard = MagicMock()
    line_mock_standard.sku = sku_standard
    line_mock_standard.line_total = Decimal("1160.00")
    line_mock_standard.quantity = Decimal("1")
    line_mock_standard.unit_price = Decimal("1160.00")
    line_mock_standard.description_snapshot = "Bandages"
    line_mock_standard.unit = "PK"

    mapped_standard = FiscalizationPipeline.map_line_tax(line_mock_standard)
    assert mapped_standard["tax_ty_cd"] == "A"
    assert mapped_standard["taxable_amt"] == Decimal("1000.00")
    assert mapped_standard["tax_amt"] == Decimal("160.00")
    assert mapped_standard["total_amt"] == Decimal("1160.00")


# ==============================================================================
# 3. VSCU Client Handshake & Transmission Mock
# ==============================================================================

def test_vscu_client_server_time(test_setup):
    profile = test_setup["profile"]
    client = VscuClient(profile)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "resultCd": "000",
        "resultMsg": "SUCCESS",
        "data": {"curTrnsDt": "20261016", "curTrnsTm": "140500"},
    }

    with patch("requests.post", return_value=mock_resp):
        res = client.check_server_time()
        assert res["success"] is True
        assert res["data"]["curTrnsDt"] == "20261016"
        profile.refresh_from_db()
        assert profile.last_sync_at is not None


def test_vscu_client_initialize_device(test_setup):
    profile = test_setup["profile"]
    client = VscuClient(profile)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "resultCd": "000",
        "resultMsg": "SUCCESS",
        "info": {
            "tin": "P051234567Z",
            "bhfId": "00",
            "dvcId": "SDC-NEW-999",
            "cmKey": "NEW-COMMUNICATION-KEY",
            "taxprNm": "Apex Healthcare Ltd",
            "bhfNm": "Headquarters",
            "mrcNo": "MRC-00123",
        },
    }

    with patch("requests.post", return_value=mock_resp):
        res = client.initialize_device()
        assert res["success"] is True
        profile.refresh_from_db()
        assert profile.is_initialized is True
        assert profile.sdc_id == "SDC-NEW-999"
        assert profile.cm_key == "NEW-COMMUNICATION-KEY"
        assert profile.taxpayer_name == "Apex Healthcare Ltd"
        assert profile.mrc_no == "MRC-00123"


# ==============================================================================
# 4. One Authoritative Fiscal Outbox on Sale Settlement
# ==============================================================================

@patch.object(PosRetailService, "_authority")
@patch.object(PosRetailService, "_catalogue_item")
def test_retail_sale_uses_the_checkout_fiscal_outbox(mock_item, mock_auth, test_setup):
    tenant = test_setup["tenant"]
    branch = test_setup["branch"]
    store = test_setup["store"]
    register = test_setup["register"]
    user = test_setup["user"]
    bday = test_setup["bday"]
    shift = test_setup["shift"]
    session = test_setup["session"]
    sku_exempt = test_setup["sku_exempt"]
    auth = MagicMock()
    auth.register = register
    auth.session = session
    auth.operator_shift = shift
    auth.business_day = bday
    mock_auth.return_value = auth

    cat_item = MagicMock()
    cat_item.resolved_price.unit_price = Decimal("500.00")
    cat_item.resolved_price.source = "DEFAULT"
    cat_item.resolved_price.reference = "REF-1"
    cat_item.resolved_price.context_hash = "CTX-1"
    cat_item.resolved_price.considered = []
    cat_item.available_quantity = Decimal("10")
    cat_item.stock_state = "IN_STOCK"
    mock_item.return_value = cat_item

    tx = PosTransaction.all_objects.create(
        tenant=tenant,
        branch=branch,
        store=store,
        register=register,
        register_session=session,
        operator_shift=shift,
        business_day=bday,
        operator=user,
        device_id="DEV-01",
        state=PosTransaction.State.READY_FOR_PAYMENT,
        currency="KES",
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
    )
    PosTransactionLine.all_objects.create(
        tenant=tenant,
        transaction=tx,
        sku=sku_exempt,
        description_snapshot="Amoxil 500mg Caps",
        unit="BX",
        quantity=Decimal("2"),
        unit_price=Decimal("500.00"),
        line_total=Decimal("1000.00"),
        price_snapshot={"unit_price": "500.00"},
    )

    user.has_capability = MagicMock(return_value=True)

    settled_tx = PosRetailService.settle_cash(
        tenant=tenant,
        transaction_id=tx.pk,
        actor=user,
        device_id="DEV-01",
        cash_received="1000.00",
        idempotency_key="test-settle-etims-1",
    )

    assert settled_tx.state == PosTransaction.State.COMPLETED
    receipt = RetailCashReceipt.all_objects.get(transaction=settled_tx)
    assert receipt.amount == Decimal("1000.00")
    fiscal = FiscalSubmission.all_objects.get(tenant=tenant, source_kind="RETAIL", source_id=settled_tx.pk)
    assert fiscal.status == "NOT_CONFIGURED"
    assert not FiscalReceipt.all_objects.filter(tenant=tenant, retail_cash_receipt=receipt).exists()


# ==============================================================================
# 5. Offline Queue Resiliency: Sale Completes Even If KRA Is Down
# ==============================================================================

@patch.object(PosRetailService, "_authority")
@patch.object(PosRetailService, "_catalogue_item")
def test_offline_resilience_keeps_sale_pending_until_vscu_is_configured(mock_item, mock_auth, test_setup):
    tenant = test_setup["tenant"]
    branch = test_setup["branch"]
    store = test_setup["store"]
    register = test_setup["register"]
    user = test_setup["user"]
    bday = test_setup["bday"]
    shift = test_setup["shift"]
    session = test_setup["session"]
    sku_exempt = test_setup["sku_exempt"]

    auth = MagicMock()
    auth.register = register
    auth.session = session
    auth.operator_shift = shift
    auth.business_day = bday
    mock_auth.return_value = auth

    cat_item = MagicMock()
    cat_item.resolved_price.unit_price = Decimal("200.00")
    cat_item.resolved_price.source = "DEFAULT"
    cat_item.resolved_price.reference = "REF-1"
    cat_item.resolved_price.context_hash = "CTX-1"
    cat_item.resolved_price.considered = []
    cat_item.available_quantity = Decimal("10")
    cat_item.stock_state = "IN_STOCK"
    mock_item.return_value = cat_item

    tx = PosTransaction.all_objects.create(
        tenant=tenant,
        branch=branch,
        store=store,
        register=register,
        register_session=session,
        operator_shift=shift,
        business_day=bday,
        operator=user,
        device_id="DEV-01",
        state=PosTransaction.State.READY_FOR_PAYMENT,
        currency="KES",
        subtotal=Decimal("200.00"),
        total=Decimal("200.00"),
    )
    PosTransactionLine.all_objects.create(
        tenant=tenant,
        transaction=tx,
        sku=sku_exempt,
        description_snapshot="Paracetamol 500mg",
        unit="BX",
        quantity=Decimal("1"),
        unit_price=Decimal("200.00"),
        line_total=Decimal("200.00"),
        price_snapshot={"unit_price": "200.00"},
    )

    user.has_capability = MagicMock(return_value=True)

    settled_tx = PosRetailService.settle_cash(
        tenant=tenant,
        transaction_id=tx.pk,
        actor=user,
        device_id="DEV-01",
        cash_received="200.00",
        idempotency_key="test-settle-offline-1",
    )

    assert settled_tx.state == PosTransaction.State.COMPLETED
    receipt = RetailCashReceipt.all_objects.get(transaction=settled_tx)
    fiscal = FiscalSubmission.all_objects.get(tenant=tenant, source_kind="RETAIL", source_id=settled_tx.pk)
    assert receipt.amount == Decimal("200.00")
    assert fiscal.status == "NOT_CONFIGURED"
    assert not fiscal.response
    assert not FiscalReceipt.all_objects.filter(tenant=tenant, retail_cash_receipt=receipt).exists()


# ==============================================================================
# 6. Taxation API Endpoints
# ==============================================================================

def test_taxation_api_profile_and_retry(test_setup):
    tenant = test_setup["tenant"]
    user = test_setup["user"]
    profile = test_setup["profile"]

    client = APIClient()
    client.force_authenticate(user=user)

    # GET profile
    res = client.get("/api/taxation/profile/", HTTP_X_TENANT_ID=str(tenant.pk))
    assert res.status_code == 200
    data = res.json()
    assert data["tin"] == "P051234567Z"
    assert data["has_cm_key"] is True

    # PATCH profile
    patch_res = client.patch(
        "/api/taxation/profile/",
        {"tin": "P059999999X", "bhf_id": "01"},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert patch_res.status_code == 200
    profile.refresh_from_db()
    assert profile.tin == "P059999999X"
    assert profile.bhf_id == "01"

    fiscal = FiscalReceipt.all_objects.create(
        tenant=tenant,
        invoice_number=99,
        submission_status=FiscalReceipt.SubmissionStatus.FAILED,
        total_amount=Decimal("500.00"),
        raw_request_payload={"tin": "P059999999X", "invcNo": 99},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "resultCd": "000",
        "resultMsg": "SUCCESS",
        "data": {
            "rcptNo": 99,
            "intrlData": "RETRY-INT",
            "rcptSign": "RETRY-SIGN",
        },
    }

    with patch("requests.post", return_value=mock_resp):
        retry_res = client.post(
            f"/api/taxation/receipts/{fiscal.pk}/retry/",
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert retry_res.status_code == 200
        assert retry_res.json()["success"] is True

        fiscal.refresh_from_db()
        assert fiscal.submission_status == FiscalReceipt.SubmissionStatus.SUBMITTED
        assert fiscal.receipt_signature == "RETRY-SIGN"


def test_taxation_profile_api_is_platform_owner_only(test_setup):
    tenant = test_setup["tenant"]
    operator = User.objects.create_user(
        username="ordinary_tenant_operator", password="password123", tenant=tenant
    )
    client = APIClient()
    client.force_authenticate(user=operator)

    response = client.get("/api/taxation/profile/", HTTP_X_TENANT_ID=str(tenant.pk))

    assert response.status_code == 403


def test_etims_queue_limit_counts_due_receipts_not_future_retries(test_setup, monkeypatch):
    tenant = test_setup["tenant"]
    future = FiscalReceipt.all_objects.create(
        tenant=tenant,
        invoice_number=201,
        submission_status=FiscalReceipt.SubmissionStatus.FAILED,
        next_retry_at=timezone.now() + timedelta(hours=1),
    )
    due = FiscalReceipt.all_objects.create(
        tenant=tenant,
        invoice_number=202,
        submission_status=FiscalReceipt.SubmissionStatus.FAILED,
        next_retry_at=timezone.now() - timedelta(minutes=1),
    )
    submitted = []
    monkeypatch.setattr(
        "apps.taxation.management.commands.process_etims_queue.FiscalizationPipeline.transmit_to_vscu",
        lambda receipt, profile: submitted.append(receipt.pk) or True,
    )

    call_command("process_etims_queue", "--limit", "1", stdout=StringIO())

    assert future.pk not in submitted
    assert submitted == [due.pk]
