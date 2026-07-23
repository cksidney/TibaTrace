import datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase

from apps.core.tenant_context import set_current_tenant_id
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.services import (
    GoodsReceivingService,
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

User = get_user_model()


class TestGoodsReceiptConcurrency(TransactionTestCase):
    """
    Tests proving that the GoodsReceivingService properly uses select_for_update
    and prevents over-receipt of PurchaseOrderLines.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Concurrency Tenant", slug="concurrency-tenant")
        set_current_tenant_id(str(self.tenant.pk))
        self.user = User.objects.create_user(username="concuser", email="conc@test.com", password="password123", tenant=self.tenant)  # nosec B106

        self.supplier = SupplierGovernanceService.create_supplier(tenant=self.tenant, supplier_code="SUP-CONC", legal_name="Conc Supplier")
        SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.user)

        self.org = Organization.objects.create(tenant=self.tenant, code="ORG-CONC", name="Conc Org")
        self.branch = Location.objects.create(tenant=self.tenant, organization=self.org, code="LOC-CONC", name="Conc Branch")

        self.df = DoseForm.objects.create(code="TAB", name="Tablet")
        self.cmp = ClinicalMedicinalProduct.objects.create(tenant=self.tenant, code="CMP-CONC", canonical_name="Conc Product", dose_form=self.df)
        self.mp = ManufacturedMedicinalProduct.objects.create(tenant=self.tenant, code="MP-CONC", brand_name="Conc Brand", clinical_product=self.cmp)
        self.pkg = PackageDefinition.objects.create(code="BOX100", description="Box 100", unit_of_measure="tab")
        self.sku = CommercialSKU.objects.create(tenant=self.tenant, sku_code="SKU-CONC-001", display_name="SKU Conc", manufactured_product=self.mp, package_definition=self.pkg)

        self.req = PurchaseRequisitionService.create_requisition(
            tenant=self.tenant, requisition_number="REQ-CONC", requesting_branch=self.branch, requester=self.user, requested_delivery_date=datetime.date.today()
        )
        PurchaseRequisitionService.add_line(requisition=self.req, sku=self.sku, requested_quantity=100)

        self.po = PurchaseOrderService.create_po_from_requisition(
            tenant=self.tenant,
            po_number="PO-CONC-100",
            supplier=self.supplier,
            requisition=self.req,
            ordering_branch=self.branch,
            order_date=datetime.date.today(),
            expected_delivery_date=datetime.date.today(),
            creator=self.user,
        )
        PurchaseOrderService.approve_po(purchase_order=self.po, approver=self.user)
        PurchaseOrderService.send_po(purchase_order=self.po)

        self.grn = GoodsReceivingService.start_goods_receipt(
            tenant=self.tenant,
            grn_number="GRN-CONC-001",
            purchase_order=self.po,
            receiving_branch=self.branch,
            receiver=self.user,
            delivery_note_number="DN-123",
        )
        self.po_line = self.po.lines.first()

    def test_over_receipt_is_prevented(self):
        """Proof that we cannot receive more than ordered sequentially."""
        # Receive 90
        GoodsReceivingService.receive_line(
            goods_receipt=self.grn,
            po_line=self.po_line,
            delivered_quantity=90,
            accepted_quantity=90,
        )

        # Attempting to receive 20 more should fail because 90 + 20 > 100
        with self.assertRaisesMessage(ValidationError, "Total received quantity cannot exceed ordered quantity"):
            GoodsReceivingService.receive_line(
                goods_receipt=self.grn,
                po_line=self.po_line,
                delivered_quantity=20,
                accepted_quantity=20,
            )

    @mock.patch("apps.procurement.services.PurchaseOrderLine.objects.select_for_update")
    def test_select_for_update_is_called(self, mock_select_for_update):
        """Proof that a database row lock is acquired during receive_line."""
        # Setup mock chain
        mock_qs = mock.MagicMock()
        mock_select_for_update.return_value = mock_qs
        mock_qs.get.return_value = self.po_line

        GoodsReceivingService.receive_line(
            goods_receipt=self.grn,
            po_line=self.po_line,
            delivered_quantity=10,
            accepted_quantity=10,
        )

        mock_select_for_update.assert_called_once()
        mock_qs.get.assert_called_once_with(pk=self.po_line.pk)
