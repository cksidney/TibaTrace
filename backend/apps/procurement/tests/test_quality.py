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
from apps.procurement.models import ReceivingInspection, SupplierQualification
from apps.procurement.services import (
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    ReceivingInspectionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_receiving_inspection_decision():
    tenant = Tenant.objects.create(name="Insp Tenant", slug="insp-tenant")
    user = User.objects.create_user(username="inspuser", email="insp@test.com", password="password123", tenant=tenant)  # nosec B106

    supplier = SupplierGovernanceService.create_supplier(tenant=tenant, supplier_code="SUP-INSP", legal_name="Insp Supplier")
    SupplierGovernanceService.approve_supplier(supplier=supplier, approver=user)
    SupplierQualification.objects.create(
        tenant=tenant, supplier=supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
    )

    org = Organization.objects.create(tenant=tenant, code="ORG-INSP", name="Insp Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-INSP", name="Insp Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-INSP", canonical_name="Insp Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-INSP", brand_name="Insp Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-INSP-001", display_name="SKU Insp", manufactured_product=mp, package_definition=pkg)

    req = PurchaseRequisitionService.create_requisition(tenant=tenant, requisition_number="REQ-INSP", requesting_branch=branch, requester=user, requested_delivery_date=datetime.date.today())
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=20)
    po = PurchaseOrderService.create_po_from_requisition(tenant=tenant, po_number="PO-INSP", supplier=supplier, requisition=req, ordering_branch=branch, order_date=datetime.date.today(), expected_delivery_date=datetime.date.today(), creator=user)
    PurchaseOrderService.approve_po(purchase_order=po, approver=user)
    PurchaseOrderService.send_po(purchase_order=po)

    grn = GoodsReceivingService.start_goods_receipt(tenant=tenant, grn_number="GRN-INSP", purchase_order=po, receiving_branch=branch, receiver=user, delivery_note_number="DN-INSP")

    inspection = ReceivingInspectionService.record_inspection(
        goods_receipt=grn, inspector=user, decision=ReceivingInspection.Decision.QUARANTINE, reason="Temperature excursion logged during transit"
    )

    assert inspection.decision == ReceivingInspection.Decision.QUARANTINE
    assert inspection.inspector == user
