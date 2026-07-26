import datetime

import pytest
from django.contrib.auth import get_user_model

from apps.core.tenant_context import set_current_tenant_id
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import ReceivedBatch, SupplierQualification
from apps.procurement.services import (
    BatchReceivingService,
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_batch_capture_and_quality_release():
    tenant = Tenant.objects.create(name="Batch Tenant", slug="batch-tenant")
    set_current_tenant_id(str(tenant.pk))
    user = User.objects.create_user(username="batchuser", email="batch@test.com", password="password123", tenant=tenant, is_platform_admin=True)  # nosec B106
    approver = User.objects.create_user(username="batchuser-app", email="batchuser-app@test.com", password="password123", tenant=tenant)  # nosec B106

    supplier = SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code="SUP-BATCH", legal_name="Batch Supplier")
    SupplierGovernanceService.approve_supplier(supplier=supplier, approver=approver)
    SupplierQualification.objects.create(
        tenant=tenant, supplier=supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
    )
    SupplierQualification.objects.create(
        tenant=tenant, supplier=supplier, qualification_type=SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
        licence_number="WDL-TEST",
        verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED,
        effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
    )

    org = Organization.objects.create(tenant=tenant, code="ORG-BAT", name="Bat Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-BAT", name="Bat Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-BAT", canonical_name="Bat Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-BAT", brand_name="Bat Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-BAT-001", display_name="SKU Bat", manufactured_product=mp, package_definition=pkg)

    req = PurchaseRequisitionService.create_requisition(tenant=tenant, requisition_number="REQ-BAT", requesting_branch=branch, requester=user, requested_delivery_date=datetime.date.today())
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=50)
    PurchaseRequisitionService.submit_requisition(requisition=req)
    PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)

    po = PurchaseOrderService.create_po_from_requisition(tenant=tenant, po_number="PO-BAT", supplier=supplier, requisition=req, ordering_branch=branch, order_date=datetime.date.today(), expected_delivery_date=datetime.date.today(), creator=user)
    PurchaseOrderService.approve_po(purchase_order=po, approver=user)
    PurchaseOrderService.send_po(purchase_order=po)

    grn = GoodsReceivingService.start_goods_receipt(tenant=tenant, grn_number="GRN-BAT", purchase_order=po, receiving_branch=branch, receiver=user, delivery_note_number="DN-BAT")
    grn_line = GoodsReceivingService.receive_line(goods_receipt=grn, po_line=po.lines.first(), delivered_quantity=50, accepted_quantity=50)

    # 1. Capture batch
    batch = BatchReceivingService.capture_batch(
        grn_line=grn_line,
        manufacturer_batch_number="BATCH-2026-X",
        expiry_date=datetime.date.today() + datetime.timedelta(days=365),
        received_quantity=50,
    )
    assert batch.quality_status == ReceivedBatch.QualityStatus.PENDING_INSPECTION

    # 2. Release batch
    released_batch = BatchReceivingService.release_batch(batch=batch, actor=user, reason="Lab analysis passed")
    assert released_batch.quality_status == ReceivedBatch.QualityStatus.RELEASED
    assert released_batch.accepted_quantity == 50
