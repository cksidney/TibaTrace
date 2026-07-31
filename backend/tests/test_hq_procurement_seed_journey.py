import pytest
from django.core.management import call_command

from apps.inventory.models import InventoryLedgerEntry
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseRequisition,
    ReceivedBatch,
    Supplier,
    SupplierQualification,
    ThreeWayMatch,
)
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_hq_seed_builds_complete_and_open_procurement_journeys(
    client,
    django_user_model,
):
    tenant = Tenant.objects.create(
        name="HQ Procurement Seed Tenant",
        slug="hq-procurement-seed",
        status=Tenant.STATUS_ACTIVE,
    )

    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0)

    supplier = Supplier.all_objects.get(
        tenant=tenant,
        supplier_code="HQ-DEMO-SUP",
    )
    assert supplier.status == Supplier.Status.APPROVED

    complete_po = PurchaseOrder.all_objects.get(
        tenant=tenant,
        po_number="HQ-DEMO-PO-COMPLETE",
    )
    assert complete_po.status in {
        PurchaseOrder.Status.FULLY_RECEIVED,
        PurchaseOrder.Status.CLOSED,
    }
    open_po = PurchaseOrder.all_objects.get(
        tenant=tenant,
        po_number="HQ-DEMO-PO-OPEN",
    )
    assert open_po.status == PurchaseOrder.Status.SENT

    receipt = GoodsReceipt.all_objects.get(
        tenant=tenant,
        grn_number="HQ-DEMO-GRN-COMPLETE",
    )
    assert receipt.status in {
        GoodsReceipt.Status.ACCEPTED,
        GoodsReceipt.Status.CLOSED,
    }
    received_batch = ReceivedBatch.all_objects.get(
        tenant=tenant,
        manufacturer_batch_number="HQ-DEMO-BATCH-COMPLETE",
    )
    assert received_batch.quality_status == ReceivedBatch.QualityStatus.RELEASED
    assert ThreeWayMatch.all_objects.filter(
        tenant=tenant,
        purchase_order=complete_po,
        goods_receipt=receipt,
    ).exists()
    assert InventoryLedgerEntry.all_objects.filter(
        tenant=tenant,
        sku=received_batch.sku,
        source_document_type="RECEIVED_BATCH",
        source_document_id=str(received_batch.pk),
    ).exists()

    tracked_models = (
        Supplier,
        SupplierQualification,
        PurchaseRequisition,
        PurchaseOrder,
        GoodsReceipt,
        ReceivedBatch,
        ThreeWayMatch,
    )
    counts_before = {
        model: model.all_objects.filter(tenant=tenant).count()
        for model in tracked_models
    }
    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0)
    counts_after = {
        model: model.all_objects.filter(tenant=tenant).count()
        for model in tracked_models
    }
    assert counts_after == counts_before

    platform_admin = django_user_model.objects.create_user(
        username="hq-procurement-platform-admin",
        password="test-password",
        is_platform_admin=True,
    )
    client.force_login(platform_admin)
    response = client.get(
        "/api/procurement/context/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert response.status_code == 200
    assert response.json()["suppliers"]
    assert response.json()["orders"]
