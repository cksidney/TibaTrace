import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.medicines.models import CommercialSKU, DoseForm, ManufacturedMedicinalProduct, PackageDefinition
from apps.organizations.models import Location, Organization
from apps.procurement.models import PurchaseRequisition
from apps.procurement.services import PurchaseRequisitionService
from apps.tenancy.models import Tenant

User = get_user_model()


@pytest.mark.django_db
def test_purchase_requisition_lifecycle_and_segregation_of_duties():
    tenant = Tenant.objects.create(name="Req Tenant", slug="req-tenant")
    requester = User.objects.create_user(username="requester", email="req@test.com", password="password123", tenant=tenant)  # nosec B106
    approver = User.objects.create_user(username="approver", email="app@test.com", password="password123", tenant=tenant)  # nosec B106

    org = Organization.objects.create(tenant=tenant, code="ORG-REQ", name="Req Org")
    branch = Location.objects.create(tenant=tenant, organization=org, code="LOC-REQ", name="Req Branch")

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    from apps.medicines.models import ClinicalMedicinalProduct
    cmp = ClinicalMedicinalProduct.objects.create(tenant=tenant, code="CMP-REQ", canonical_name="Req Product", dose_form=df)
    mp = ManufacturedMedicinalProduct.objects.create(tenant=tenant, code="MP-REQ", brand_name="Req Brand", clinical_product=cmp)
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
    sku = CommercialSKU.objects.create(tenant=tenant, sku_code="SKU-REQ-001", display_name="SKU Req", manufactured_product=mp, package_definition=pkg)

    # 1. Create requisition
    req = PurchaseRequisitionService.create_requisition(
        tenant=tenant,
        requisition_number="REQ-001",
        requesting_branch=branch,
        requester=requester,
        requested_delivery_date=datetime.date.today() + datetime.timedelta(days=5),
        justification="Low stock level",
    )
    assert req.status == PurchaseRequisition.Status.DRAFT

    # 2. Add line
    line = PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=100)
    # A draft is the requester's working copy. Handing it to an approver is a
    # deliberate act, so a draft cannot be approved straight from creation.
    PurchaseRequisitionService.submit_requisition(requisition=req)
    assert line.requested_quantity == 100

    # 3. Segregation of duties check: Requester cannot approve their own requisition
    with pytest.raises(ValidationError):
        PurchaseRequisitionService.approve_requisition(requisition=req, approver=requester)

    # 4. Approver approves requisition
    approved_req = PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)
    assert approved_req.status == PurchaseRequisition.Status.APPROVED
    assert approved_req.approved_by == approver
