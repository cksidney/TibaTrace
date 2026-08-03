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
from apps.procurement.models import PurchaseOrder, SupplierQualification
from apps.procurement.services import PurchaseOrderService, PurchaseRequisitionService, SupplierGovernanceService
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_purchase_order_creation_and_approval():
    tenant = Tenant.objects.create(name="PO Tenant", slug="po-tenant")
    set_current_tenant_id(str(tenant.pk))
    user = User.objects.create_user(username="pouser", email="po@test.com", password="password123", tenant=tenant)  # nosec B106
    approver = User.objects.create_user(username="pouser-app", email="pouser-app@test.com", password="password123", tenant=tenant)  # nosec B106

    supplier = SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code="SUP-PO", legal_name="PO Supplier")
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

    org = Organization.objects.create(tenant=tenant, code="ORG-PO", name="PO Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-PO", name="PO Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-PO", canonical_name="PO Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-PO", brand_name="PO Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-PO-001", display_name="SKU PO", manufactured_product=mp, package_definition=pkg)

    req = PurchaseRequisitionService.create_requisition(
        tenant=tenant,
        requisition_number="REQ-PO-01",
        requesting_branch=branch,
        requester=user,
        requested_delivery_date=datetime.date.today() + datetime.timedelta(days=7),
    )
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=50)
    PurchaseRequisitionService.submit_requisition(requisition=req)
    PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)

    # Create PO from requisition
    po = PurchaseOrderService.create_po_from_requisition(
        tenant=tenant,
        po_number="PO-2026-999",
        supplier=supplier,
        requisition=req,
        ordering_branch=branch,
        order_date=datetime.date.today(),
        expected_delivery_date=datetime.date.today() + datetime.timedelta(days=5),
        creator=user,
    )
    assert po.status == PurchaseOrder.Status.DRAFT
    assert po.lines.count() == 1

    # Approve PO
    approved_po = PurchaseOrderService.approve_po(purchase_order=po, approver=approver)
    assert approved_po.status == PurchaseOrder.Status.APPROVED

    # Send PO
    sent_po = PurchaseOrderService.send_po(purchase_order=approved_po)
    assert sent_po.status == PurchaseOrder.Status.SENT
