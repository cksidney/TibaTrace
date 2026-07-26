import uuid

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
from apps.procurement.models import GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, Supplier
from apps.procurement.services import GoodsReceivingService
from apps.tenancy.models import Tenant


class ProcurementIdempotencyTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        set_current_tenant_id(str(self.tenant.pk))
        
        self.user = User.objects.create_user(username="idemp_user", email="idemp@test.com", password="password123", tenant=self.tenant)  # nosec B106
        
        self.org = Organization.objects.create(tenant=self.tenant, code="ORG", name="Org")
        self.branch = Location.objects.create(tenant=self.tenant, organization=self.org, code="LOC", name="Loc")
        
        self.supplier = Supplier.objects.create(tenant=self.tenant, supplier_code="SUP-IDEMP", legal_name="Supplier", status=Supplier.Status.APPROVED)
        
        form = DoseForm.objects.create(code="TAB", name="Tablet")
        clin = ClinicalMedicinalProduct.objects.create(tenant=self.tenant, code="CLIN", canonical_name="Clin", dose_form=form)
        man = ManufacturedMedicinalProduct.objects.create(tenant=self.tenant, code="MAN", brand_name="Man", clinical_product=clin)
        pkg = PackageDefinition.objects.create(code="BOX", description="Box", unit_of_measure="box")
        self.sku = CommercialSKU.objects.create(tenant=self.tenant, sku_code="SKU-1", display_name="SKU 1", manufactured_product=man, package_definition=pkg)
        
        self.po = PurchaseOrder.objects.create(
            tenant=self.tenant,
            po_number="PO-123",
            supplier=self.supplier,
            ordering_branch=self.branch,
            order_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate(),
            status=PurchaseOrder.Status.SENT
        )
        self.po_line = PurchaseOrderLine.objects.create(
            tenant=self.tenant,
            purchase_order=self.po,
            sku=self.sku,
            ordered_quantity=100,
            unit_price=10.0,
            total_price=1000.0
        )
        
        self.grn = GoodsReceivingService.start_goods_receipt(
            tenant=self.tenant,
            grn_number="GRN-123",
            purchase_order=self.po,
            receiving_branch=self.branch,
            receiver=self.user,
            delivery_note_number="DN-123"
        )

    def test_receiving_idempotency(self):
        idempotency_key = f"rec-{uuid.uuid4()}"
        
        # First request
        line1 = GoodsReceivingService.receive_line(
            goods_receipt=self.grn,
            po_line=self.po_line,
            delivered_quantity=20,
            accepted_quantity=20,
            idempotency_key=idempotency_key
        )
        self.assertEqual(line1.delivered_quantity, 20)
        
        self.po_line.refresh_from_db()
        self.assertEqual(self.po_line.received_quantity, 20)
        
        # Second request with same idempotency key (retry)
        line2 = GoodsReceivingService.receive_line(
            goods_receipt=self.grn,
            po_line=self.po_line,
            delivered_quantity=20,
            accepted_quantity=20,
            idempotency_key=idempotency_key
        )
        
        self.assertEqual(line1.pk, line2.pk)
        
        # Quantities should NOT be double-counted
        self.po_line.refresh_from_db()
        self.assertEqual(self.po_line.received_quantity, 20)
        self.assertEqual(GoodsReceiptLine.objects.filter(goods_receipt=self.grn).count(), 1)
