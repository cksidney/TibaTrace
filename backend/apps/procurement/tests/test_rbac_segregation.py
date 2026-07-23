import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.tenant_context import set_current_tenant_id
from apps.organizations.models import Location, Organization
from apps.procurement.models import PurchaseRequisition
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

    def test_requester_cannot_approve_own_requisition(self):
        req = PurchaseRequisitionService.create_requisition(
            tenant=self.tenant,
            requisition_number="REQ-RBAC-001",
            requesting_branch=self.branch,
            requester=self.requester_user,
            requested_delivery_date=datetime.date.today()
        )
        
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
