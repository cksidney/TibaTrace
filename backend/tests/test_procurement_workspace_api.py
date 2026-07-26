from datetime import date, timedelta

import pytest

from apps.inventory.models import InventoryBalance, InventoryLocation
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import SupplierQualification
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_procurement_workspace_runs_procure_to_stock_lifecycle(client, django_user_model):
    tenant = Tenant.objects.create(name="Procurement API Tenant", slug="procurement-api")
    requester = django_user_model.objects.create_user(
        username="procurement-requester",
        password="procurement-requester-password",
        tenant=tenant,
    )
    approver = django_user_model.objects.create_user(
        username="procurement-platform-approver",
        password="procurement-platform-approver-password",
        is_platform_admin=True,
    )

    organization = Organization.all_objects.create(
        tenant=tenant,
        code="HQ",
        name="Procurement HQ",
    )
    branch = Location.all_objects.create(
        tenant=tenant,
        organization=organization,
        code="MAIN",
        name="Main Pharmacy",
    )
    inventory_location = InventoryLocation.all_objects.create(
        tenant=tenant,
        branch=branch,
        location_code="MAIN-STOCK",
        name="Main released stock",
        location_type=InventoryLocation.LocationType.STORE,
    )

    dose_form = DoseForm.objects.create(code="TAB-PROC", name="Procurement tablet")
    package = PackageDefinition.objects.create(
        code="PACK-PROC",
        description="Procurement pack",
        unit_of_measure="pack",
    )
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="CMP-PROC",
        canonical_name="Procurement Product",
        dose_form=dose_form,
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant,
        code="MMP-PROC",
        brand_name="Procurement Brand",
        clinical_product=clinical,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant,
        sku_code="SKU-PROC",
        display_name="Procurement Brand x 10",
        manufactured_product=manufactured,
        package_definition=package,
    )

    client.force_login(approver)
    tenant_header = {"HTTP_X_TENANT_ID": str(tenant.pk)}
    supplier_response = client.post(
        "/api/procurement/suppliers/",
        {
            "supplier_code": "SUP-PROC",
            "legal_name": "Procurement Supplier Ltd",
            "risk_category": "LOW",
            "payment_terms": "NET30",
            "default_currency": "KES",
        },
        content_type="application/json",
        **tenant_header,
    )
    assert supplier_response.status_code == 201
    supplier_id = supplier_response.json()["id"]

    for qualification_type in (
        SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
    ):
        qualification_response = client.post(
            "/api/procurement/supplier-qualifications/",
            {
                "supplier": supplier_id,
                "qualification_type": qualification_type,
                "licence_number": f"LIC-{qualification_type}",
                "issuing_authority": "PPB",
                "effective_date": str(date.today() - timedelta(days=1)),
                "expiry_date": str(date.today() + timedelta(days=365)),
            },
            content_type="application/json",
            **tenant_header,
        )
        assert qualification_response.status_code == 201
        verification_response = client.post(
            f"/api/procurement/supplier-qualifications/{qualification_response.json()['id']}/verify/",
            content_type="application/json",
            **tenant_header,
        )
        assert verification_response.status_code == 200

    approved_supplier = client.post(
        f"/api/procurement/suppliers/{supplier_id}/approve/",
        {"reason": "Qualified supplier"},
        content_type="application/json",
        **tenant_header,
    )
    assert approved_supplier.status_code == 200

    client.force_login(requester)
    requisition_response = client.post(
        "/api/procurement/requisitions/",
        {
            "requesting_branch": str(branch.pk),
            "requested_delivery_date": str(date.today() + timedelta(days=7)),
            "priority": "HIGH",
            "justification": "Replenish essential stock",
            "lines": [
                {
                    "sku": str(sku.pk),
                    "requested_quantity": 20,
                    "purchase_unit": "pack",
                }
            ],
        },
        content_type="application/json",
        **tenant_header,
    )
    assert requisition_response.status_code == 201
    requisition = requisition_response.json()
    requisition_id = requisition["id"]
    requisition_line_id = requisition["lines"][0]["id"]

    submitted = client.post(
        f"/api/procurement/requisitions/{requisition_id}/submit/",
        content_type="application/json",
        **tenant_header,
    )
    assert submitted.status_code == 200

    client.force_login(approver)
    approved_requisition = client.post(
        f"/api/procurement/requisitions/{requisition_id}/approve/",
        content_type="application/json",
        **tenant_header,
    )
    assert approved_requisition.status_code == 200

    order_response = client.post(
        "/api/procurement/purchase-orders/",
        {
            "supplier": supplier_id,
            "originating_requisition": requisition_id,
            "ordering_branch": str(branch.pk),
            "expected_delivery_date": str(date.today() + timedelta(days=5)),
            "currency": "KES",
            "lines": [
                {
                    "requisition_line": requisition_line_id,
                    "quantity": 20,
                    "unit_cost": "125.00",
                }
            ],
        },
        content_type="application/json",
        **tenant_header,
    )
    assert order_response.status_code == 201
    order = order_response.json()
    order_id = order["id"]
    order_line_id = order["lines"][0]["id"]
    assert order["total_gross"] == "2500.00"

    assert client.post(
        f"/api/procurement/purchase-orders/{order_id}/approve/",
        content_type="application/json",
        **tenant_header,
    ).status_code == 200
    assert client.post(
        f"/api/procurement/purchase-orders/{order_id}/send/",
        content_type="application/json",
        **tenant_header,
    ).status_code == 200

    receipt_response = client.post(
        "/api/procurement/goods-receipts/",
        {
            "purchase_order": order_id,
            "receiving_branch": str(branch.pk),
            "delivery_note_number": "DN-PROC-001",
        },
        content_type="application/json",
        **tenant_header,
    )
    assert receipt_response.status_code == 201
    receipt_id = receipt_response.json()["id"]

    batch_response = client.post(
        f"/api/procurement/goods-receipts/{receipt_id}/receive-batch/",
        {
            "po_line": order_line_id,
            "manufacturer_batch_number": "BATCH-PROC-001",
            "expiry_date": str(date.today() + timedelta(days=365)),
            "received_quantity": 20,
            "idempotency_key": "procurement-api-receipt-1",
        },
        content_type="application/json",
        **tenant_header,
    )
    assert batch_response.status_code == 201
    batch_id = batch_response.json()["id"]

    inspection_response = client.post(
        f"/api/procurement/goods-receipts/{receipt_id}/inspect/",
        {
            "decision": "QUARANTINE",
            "reason": "Awaiting quality release",
            "temperature_excursion": False,
        },
        content_type="application/json",
        **tenant_header,
    )
    assert inspection_response.status_code == 201

    release_response = client.post(
        f"/api/procurement/received-batches/{batch_id}/release/",
        {
            "reason": "Packaging, batch and expiry verified",
            "quantity": 20,
            "inventory_location": str(inventory_location.pk),
        },
        content_type="application/json",
        **tenant_header,
    )
    assert release_response.status_code == 200
    assert release_response.json()["quality_status"] == "RELEASED"
    balance = InventoryBalance.all_objects.get(
        tenant=tenant,
        location=inventory_location,
        sku=sku,
    )
    assert balance.available == 20

    closed = client.post(
        f"/api/procurement/goods-receipts/{receipt_id}/close/",
        content_type="application/json",
        **tenant_header,
    )
    assert closed.status_code == 200

    match_response = client.post(
        "/api/procurement/matching/",
        {
            "purchase_order": order_id,
            "goods_receipt": receipt_id,
            "invoice_reference": "INV-PROC-001",
            "invoice_amount": "2500.00",
        },
        content_type="application/json",
        **tenant_header,
    )
    assert match_response.status_code == 201
    assert match_response.json()["matching_status"] == "MATCHED"

    return_response = client.post(
        "/api/procurement/supplier-returns/",
        {
            "return_number": "RET-PROC-001",
            "goods_receipt": receipt_id,
            "reason": "Supplier recall",
            "lines": [{"sku": str(sku.pk), "quantity": 1}],
        },
        content_type="application/json",
        **tenant_header,
    )
    assert return_response.status_code == 201
    assert return_response.json()["status"] == "REQUESTED"
