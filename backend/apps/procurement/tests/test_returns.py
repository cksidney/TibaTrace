import datetime

import pytest
from django.contrib.auth import get_user_model

from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import SupplierQualification, SupplierReturn
from apps.procurement.services import (
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
    SupplierReturnService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_supplier_return_request():
    tenant = Tenant.objects.create(name="Ret Tenant", slug="ret-tenant")
    user = User.objects.create_user(username="retuser", email="ret@test.com", password="password123", tenant=tenant)  # nosec B106

    supplier = SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code="SUP-RET", legal_name="Ret Supplier")
    SupplierGovernanceService.approve_supplier(supplier=supplier, approver=user)
    SupplierQualification.objects.create(
        tenant=tenant, supplier=supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
    )

    org = Organization.objects.create(tenant=tenant, code="ORG-RET", name="Ret Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-RET", name="Ret Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-RET", canonical_name="Ret Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-RET", brand_name="Ret Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-RET-001", display_name="SKU Ret", manufactured_product=mp, package_definition=pkg)

    req = PurchaseRequisitionService.create_requisition(tenant=tenant, requisition_number="REQ-RET", requesting_branch=branch, requester=user, requested_delivery_date=datetime.date.today())
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=10)
    po = PurchaseOrderService.create_po_from_requisition(tenant=tenant, po_number="PO-RET", supplier=supplier, requisition=req, ordering_branch=branch, order_date=datetime.date.today(), expected_delivery_date=datetime.date.today(), creator=user)
    PurchaseOrderService.approve_po(purchase_order=po, approver=user)
    PurchaseOrderService.send_po(purchase_order=po)

    grn = GoodsReceivingService.start_goods_receipt(tenant=tenant, grn_number="GRN-RET", purchase_order=po, receiving_branch=branch, receiver=user, delivery_note_number="DN-RET")

    ret = SupplierReturnService.request_return(
        tenant=tenant, return_number="RET-001", goods_receipt=grn, reason="Defective primary packaging"
    )

    assert ret.status == SupplierReturn.Status.REQUESTED
    assert ret.supplier == supplier
