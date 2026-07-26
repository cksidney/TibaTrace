import decimal

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
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    ThreeWayMatch,
)
from apps.procurement.services import ProcurementMatchingService
from apps.tenancy.models import Tenant


class ThreeWayMatchingTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        set_current_tenant_id(str(self.tenant.pk))
        
        self.user = User.objects.create_user(username="tw_user", email="tw@test.com", password="pwd", tenant=self.tenant)  # nosec B106
        
        self.org = Organization.objects.create(tenant=self.tenant, code="ORG", name="Org")
        self.branch = Location.objects.create(tenant=self.tenant, organization=self.org, code="LOC", name="Loc")
        
        self.supplier = Supplier.objects.create(tenant=self.tenant, supplier_code="SUP-TW", legal_name="Supplier", status=Supplier.Status.APPROVED)
        
        form = DoseForm.objects.create(code="TAB", name="Tablet")
        clin = ClinicalMedicinalProduct.objects.create(tenant=self.tenant, code="CLIN", canonical_name="Clin", dose_form=form)
        man = ManufacturedMedicinalProduct.objects.create(tenant=self.tenant, code="MAN", brand_name="Man", clinical_product=clin)
        pkg = PackageDefinition.objects.create(code="BOX", description="Box", unit_of_measure="box")
        self.sku = CommercialSKU.objects.create(tenant=self.tenant, sku_code="SKU-1", display_name="SKU 1", manufactured_product=man, package_definition=pkg)
        
        self.po = PurchaseOrder.objects.create(tenant=self.tenant, po_number="PO-TW", supplier=self.supplier, ordering_branch=self.branch, order_date=timezone.localdate(), expected_delivery_date=timezone.localdate(), status=PurchaseOrder.Status.SENT)
        self.po_line = PurchaseOrderLine.objects.create(tenant=self.tenant, purchase_order=self.po, sku=self.sku, ordered_quantity=100, unit_price=10.0, total_price=1000.0)
        self.grn = GoodsReceipt.objects.create(tenant=self.tenant, grn_number="GRN-TW", purchase_order=self.po, supplier=self.supplier, receiving_branch=self.branch, received_by=self.user, delivery_note_number="DN-TW", arrival_time=timezone.now(), status=GoodsReceipt.Status.ACCEPTED)
        self.grn_line = GoodsReceiptLine.objects.create(tenant=self.tenant, goods_receipt=self.grn, po_line=self.po_line, sku=self.sku, delivered_quantity=100, accepted_quantity=100)

    def test_reconcile_exact_match(self):
        match = ProcurementMatchingService.reconcile_three_way_match(
            tenant=self.tenant,
            purchase_order=self.po,
            goods_receipt=self.grn,
            invoice_reference="INV-123"
        )
        self.assertEqual(match.matching_status, ThreeWayMatch.MatchingStatus.MATCHED)
        self.assertEqual(match.invoice_reference, "INV-123")
        self.assertEqual(match.quantity_variance, 0)
        self.assertEqual(match.price_variance, decimal.Decimal("0.00"))
