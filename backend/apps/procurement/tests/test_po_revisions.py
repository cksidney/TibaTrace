from django.test import TestCase
from django.utils import timezone

from apps.core.tenant_context import set_current_tenant_id
from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderRevision, Supplier
from apps.procurement.services import PurchaseOrderService
from apps.tenancy.models import Tenant


class PurchaseOrderRevisionTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        set_current_tenant_id(str(self.tenant.pk))
        
        self.user = User.objects.create_user(username="rev_user", email="rev@test.com", password="pwd", tenant=self.tenant)  # nosec B106
        
        self.org = Organization.objects.create(tenant=self.tenant, code="ORG", name="Org")
        self.branch = Location.objects.create(tenant=self.tenant, organization=self.org, code="LOC", name="Loc")
        
        self.supplier = Supplier.objects.create(tenant=self.tenant, supplier_code="SUP-REV", legal_name="Supplier", status=Supplier.Status.APPROVED)
        
        form = DoseForm.objects.create(code="TAB", name="Tablet")
        clin = ClinicalMedicinalProduct.objects.create(tenant=self.tenant, code="CLIN", canonical_name="Clin", dose_form=form)
        man = ManufacturedMedicinalProduct.objects.create(tenant=self.tenant, code="MAN", brand_name="Man", clinical_product=clin)
        pkg = PackageDefinition.objects.create(code="BOX", description="Box", unit_of_measure="box")
        self.sku = CommercialSKU.objects.create(tenant=self.tenant, sku_code="SKU-1", display_name="SKU 1", manufactured_product=man, package_definition=pkg)
        
        self.po = PurchaseOrder.objects.create(
            tenant=self.tenant,
            po_number="PO-REV-1",
            supplier=self.supplier,
            ordering_branch=self.branch,
            order_date=timezone.now().date(),
            expected_delivery_date=timezone.now().date(),
            status=PurchaseOrder.Status.SENT,
            total_net=1000.0
        )
        self.po_line = PurchaseOrderLine.objects.create(
            tenant=self.tenant,
            purchase_order=self.po,
            sku=self.sku,
            ordered_quantity=100,
            unit_price=10.0,
            total_price=1000.0
        )

    def test_po_revision_creates_snapshot_and_resets_status(self):
        original_net = self.po.total_net
        
        PurchaseOrderService.revise_purchase_order(
            purchase_order=self.po,
            actor=self.user,
            change_reason="Price updated",
            total_net=1200.0
        )
        
        self.po.refresh_from_db()
        self.assertEqual(self.po.revision_number, 2)
        self.assertEqual(self.po.status, PurchaseOrder.Status.SUBMITTED)
        self.assertEqual(self.po.total_net, 1200.0)
        
        # Verify snapshot
        revision = PurchaseOrderRevision.objects.filter(purchase_order=self.po).first()
        self.assertIsNotNone(revision)
        self.assertEqual(revision.revision_number, 1)
        self.assertEqual(revision.change_reason, "Price updated")
        self.assertEqual(revision.actor, self.user)
        self.assertEqual(float(revision.previous_snapshot["total_net"]), float(original_net))
