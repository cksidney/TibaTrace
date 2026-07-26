import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.tenant_context import set_current_tenant_id
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import PurchaseRequisition, SupplierQualification
from apps.procurement.services import (
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


class TestSegregationOfDuties(TestCase):
    """
    Tests proving that procurement roles and authorities are strictly separated.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="RBAC Tenant", slug="rbac-tenant")
        set_current_tenant_id(str(self.tenant.pk))
        
        self.requester_user = User.objects.create_user(username="requester", email="req@test.com", password="pwd", tenant=self.tenant)  # nosec B106
        self.approver_user = User.objects.create_user(username="approver", email="app@test.com", password="pwd", tenant=self.tenant)  # nosec B106
        
        self.org = Organization.objects.create(tenant=self.tenant, code="ORG-RBAC", name="RBAC Org")
        self.branch = Location.objects.create(tenant=self.tenant, organization=self.org, code="LOC-RBAC", name="RBAC Branch")
        
        self.supplier = SupplierGovernanceService.create_supplier(tenant=self.tenant, supplier_code="SUP-RBAC", legal_name="RBAC Supplier")
        SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.approver_user)
        SupplierQualification.objects.create(
            tenant=self.tenant, supplier=self.supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
        )
        # A pharmaceutical supplier needs a dealer licence as well as a company
        # registration before it may be sent an order.
        SupplierQualification.objects.create(
            tenant=self.tenant, supplier=self.supplier, qualification_type=SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
            licence_number="WDL-RBAC",
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(), expiry_date=datetime.date.today() + datetime.timedelta(days=365)
        )

        # A requisition needs something to requisition, and a purchase order
        # needs a requisition with lines.
        dose_form = DoseForm.objects.create(code="TAB-RBAC", name="Tablet")
        clinical_product = ClinicalMedicinalProduct.objects.create(tenant=self.tenant, code="CMP-RBAC", canonical_name="RBAC Product", dose_form=dose_form)
        manufactured = ManufacturedMedicinalProduct.objects.create(tenant=self.tenant, code="MP-RBAC", brand_name="RBAC Brand", clinical_product=clinical_product)
        package = PackageDefinition.objects.create(code="BOX-RBAC", description="Box 100", unit_of_measure="tab")
        self.sku = CommercialSKU.objects.create(tenant=self.tenant, sku_code="SKU-RBAC-001", display_name="SKU RBAC", manufactured_product=manufactured, package_definition=package)

    def test_requester_cannot_approve_own_requisition(self):
        req = PurchaseRequisitionService.create_requisition(
            tenant=self.tenant,
            requisition_number="REQ-RBAC-001",
            requesting_branch=self.branch,
            requester=self.requester_user,
            requested_delivery_date=datetime.date.today()
        )
        PurchaseRequisitionService.add_line(requisition=req, sku=self.sku, requested_quantity=10)
        PurchaseRequisitionService.submit_requisition(requisition=req)

        # Requester trying to approve their own requisition
        with self.assertRaisesMessage(ValidationError, "Requester cannot approve their own purchase requisition"):
            PurchaseRequisitionService.approve_requisition(requisition=req, approver=self.requester_user)
            
        # A different user can approve it
        PurchaseRequisitionService.approve_requisition(requisition=req, approver=self.approver_user)
        self.assertEqual(req.status, PurchaseRequisition.Status.APPROVED)

    def test_po_cannot_be_approved_for_suspended_supplier(self):
        req = PurchaseRequisitionService.create_requisition(
            tenant=self.tenant,
            requisition_number="REQ-RBAC-002",
            requesting_branch=self.branch,
            requester=self.requester_user,
            requested_delivery_date=datetime.date.today()
        )
        PurchaseRequisitionService.add_line(requisition=req, sku=self.sku, requested_quantity=10)
        PurchaseRequisitionService.submit_requisition(requisition=req)
        PurchaseRequisitionService.approve_requisition(requisition=req, approver=self.approver_user)

        po = PurchaseOrderService.create_po_from_requisition(
            tenant=self.tenant,
            po_number="PO-RBAC-001",
            supplier=self.supplier,
            requisition=req,
            ordering_branch=self.branch,
            order_date=datetime.date.today(),
            expected_delivery_date=datetime.date.today(),
            creator=self.requester_user,
        )
        
        # Suspend the supplier AFTER the PO is created but BEFORE it is approved
        SupplierGovernanceService.suspend_supplier(supplier=self.supplier, reason="Compliance violation")
        
        # Attempting to approve the PO should fail because supplier is suspended
        with self.assertRaisesMessage(ValidationError, "Cannot approve PO for a supplier that is not APPROVED or ACTIVE"):
            PurchaseOrderService.approve_po(purchase_order=po, approver=self.approver_user)
