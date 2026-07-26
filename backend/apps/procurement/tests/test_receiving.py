import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.core.tenant_context import set_current_tenant_id
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import GoodsReceipt, PurchaseOrder, SupplierQualification
from apps.procurement.services import (
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_goods_receiving_workflow_and_tolerances():
    tenant = Tenant.objects.create(name="GRN Tenant", slug="grn-tenant")
    set_current_tenant_id(str(tenant.pk))
    user = User.objects.create_user(username="grnuser", email="grn@test.com", password="password123", tenant=tenant)  # nosec B106
    approver = User.objects.create_user(username="grnuser-app", email="grnuser-app@test.com", password="password123", tenant=tenant)  # nosec B106

    supplier = SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code="SUP-GRN", legal_name="GRN Supplier")
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

    org = Organization.objects.create(tenant=tenant, code="ORG-GRN", name="GRN Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-GRN", name="GRN Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-GRN", canonical_name="GRN Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-GRN", brand_name="GRN Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-GRN-001", display_name="SKU GRN", manufactured_product=mp, package_definition=pkg)

    req = PurchaseRequisitionService.create_requisition(
        tenant=tenant, requisition_number="REQ-GRN", requesting_branch=branch, requester=user, requested_delivery_date=datetime.date.today()
    )
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=100)
    PurchaseRequisitionService.submit_requisition(requisition=req)
    PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)

    po = PurchaseOrderService.create_po_from_requisition(
        tenant=tenant,
        po_number="PO-GRN-100",
        supplier=supplier,
        requisition=req,
        ordering_branch=branch,
        order_date=datetime.date.today(),
        expected_delivery_date=datetime.date.today(),
        creator=user,
    )
    PurchaseOrderService.approve_po(purchase_order=po, approver=user)
    PurchaseOrderService.send_po(purchase_order=po)

    # 1. Start GRN
    grn = GoodsReceivingService.start_goods_receipt(
        tenant=tenant,
        grn_number="GRN-001",
        purchase_order=po,
        receiving_branch=branch,
        receiver=user,
        delivery_note_number="DN-999",
    )
    assert grn.status == GoodsReceipt.Status.RECEIVING

    # 2. Invalid line quantities check
    po_line = po.lines.first()
    with pytest.raises(ValidationError):
        GoodsReceivingService.receive_line(
            goods_receipt=grn,
            po_line=po_line,
            delivered_quantity=100,
            accepted_quantity=80,
            quarantined_quantity=20,
            rejected_quantity=10,  # 80+20+10 = 110 > 100
        )

    # 3. Valid line receiving
    grn_line = GoodsReceivingService.receive_line(
        goods_receipt=grn,
        po_line=po_line,
        delivered_quantity=100,
        accepted_quantity=90,
        rejected_quantity=10,
        discrepancy_reason="10 damaged boxes",
    )
    assert grn_line.delivered_quantity == 100
    assert grn_line.accepted_quantity == 90

    # 4. Close GRN
    closed_grn = GoodsReceivingService.close_goods_receipt(goods_receipt=grn)
    assert closed_grn.status == GoodsReceipt.Status.ACCEPTED
    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.FULLY_RECEIVED
