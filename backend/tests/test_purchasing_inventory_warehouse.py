from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.identity.models import User
from apps.inventory.models import InventoryLocation
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import GoodsReceipt, PurchaseOrder, Supplier, ThreeWayMatch
from apps.procurement.services import ProcurementService, QualityService, ReceivingService, ThreeWayMatchService
from apps.tenancy.models import Tenant


@pytest.mark.django_db
class TestPurchasingInventoryWarehouse:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.tenant = Tenant.objects.create(name="Tenant Test", slug="tenant-test", status=Tenant.STATUS_ACTIVE)
        # A goods receipt records who received it: received_by is NOT NULL, so
        # there is no such thing as an anonymous delivery.
        self.receiver = User.objects.create_user(
            username="receiver", password="pw-receiving-test", tenant=self.tenant  # nosec B106
        )
        # A separate person inspects what arrived. An inspection is a named
        # judgement, so the service refuses an anonymous one.
        self.inspector = User.objects.create_user(
            username="inspector", password="pw-inspection-test", tenant=self.tenant  # nosec B106
        )
        self.org = Organization.all_objects.create(tenant=self.tenant, code="ORG1", name="Org 1")
        self.branch1 = Location.all_objects.create(tenant=self.tenant, organization=self.org, code="B1", name="Branch 1", location_type="BRANCH")
        self.branch2 = Location.all_objects.create(tenant=self.tenant, organization=self.org, code="B2", name="Branch 2", location_type="BRANCH")

        # The catalogue is four layers, not one: a substance is the ingredient, a
        # clinical product is what was prescribed, a manufactured product is the
        # brand, and only the SKU is the pack that can be ordered or received.
        # A SKU carries no strength or dose form of its own -- it reaches them
        # through the manufactured product.
        substance = ActiveSubstance.all_objects.create(
            is_global=True, code="SUB-PARA", canonical_name="Paracetamol",
            display_name="Paracetamol", search_name="paracetamol",
        )
        form = DoseForm.objects.create(name="Tablet", code="TAB")
        pack = PackageDefinition.objects.create(
            code="PACK-100", description="Pack of 100", unit_of_measure="pack",
            quantity_in_parent=100,
        )

        clinical = ClinicalMedicinalProduct.all_objects.create(
            tenant=self.tenant, code="CMP-PARA-500",
            canonical_name="Paracetamol 500mg", dose_form=form,
        )
        IngredientComposition.objects.create(
            clinical_product=clinical, active_substance=substance,
            numerator_value=Decimal("500"), numerator_unit="mg",
        )
        manufactured = ManufacturedMedicinalProduct.all_objects.create(
            tenant=self.tenant, code="MP-PARA-500", brand_name="Para 500mg",
            clinical_product=clinical,
        )

        self.sku = CommercialSKU.all_objects.create(
            tenant=self.tenant,
            sku_code="SKU-PARA-500",
            display_name="Para 500mg x100",
            manufactured_product=manufactured,
            package_definition=pack,
        )

        self.supplier = Supplier.all_objects.create(
            tenant=self.tenant,
            supplier_code="SUP-001",
            legal_name="Test Supplier Ltd",
            status=Supplier.Status.APPROVED,
        )

        self.loc1 = InventoryLocation.all_objects.create(
            tenant=self.tenant, branch=self.branch1, location_code="LOC1", name="Main Warehouse",
            location_type=InventoryLocation.LocationType.RECEIVING,
            # Goods arrive quarantined pending inspection, so a receiving bay
            # that cannot hold quarantined stock cannot take a delivery.
            quarantine_capability=True,
        )
        self.loc2 = InventoryLocation.all_objects.create(
            tenant=self.tenant, branch=self.branch2, location_code="LOC2", name="Kisumu Store",
            location_type=InventoryLocation.LocationType.DISPENSARY,
        )

    def test_purchase_order_lifecycle(self):
        po = ProcurementService.create_purchase_order(
            tenant=self.tenant,
            supplier=self.supplier,
            ordering_branch=self.branch1,
            lines_data=[{"sku": self.sku, "quantity": 50, "unit_cost": Decimal("100.00")}],
            created_by=None,
        )
        assert po.status == PurchaseOrder.Status.DRAFT
        assert po.total_gross == Decimal("5000.00")

        ProcurementService.approve_purchase_order(purchase_order=po, approver=None)
        assert po.status == PurchaseOrder.Status.APPROVED

    def test_scan_to_receive_and_grn_posting(self):
        po = ProcurementService.create_purchase_order(
            tenant=self.tenant,
            supplier=self.supplier,
            ordering_branch=self.branch1,
            lines_data=[{"sku": self.sku, "quantity": 20, "unit_cost": Decimal("150.00")}],
            created_by=None,
        )
        ProcurementService.approve_purchase_order(purchase_order=po, approver=None)
        # Receiving is refused for an order that was never sent: goods cannot
        # arrive against a commitment the supplier has not been given.
        ProcurementService.send_po(purchase_order=po)

        session = ReceivingService.open_receiving_session(
            tenant=self.tenant, purchase_order=po, branch=self.branch1, delivery_note_number="DN-101", received_by=None
        )

        ReceivingService.record_scan(
            session=session,
            sku=self.sku,
            scanned_barcode="123456789",
            batch_number="BATCH-001",
            expiry_date=timezone.now().date() + timedelta(days=180),
            scanned_quantity=20,
        )

        grn = ReceivingService.post_goods_receipt_note(session=session, destination_location=self.loc1, actor=self.receiver)
        assert grn.status == GoodsReceipt.Status.RECEIVED
        assert GoodsReceipt.all_objects.filter(tenant=self.tenant).count() == 1

        QualityService.record_inspection(
            goods_receipt=grn,
            inspector=self.inspector,
            decision="RELEASE",
            reason="Seals intact, quantities and expiry dates match the delivery note.",
        )
        match = ThreeWayMatchService.perform_three_way_match(
            purchase_order=po, goods_receipt=grn, invoice_reference="INV-101", invoice_amount=Decimal("3000.00")
        )
        assert match.matching_status == ThreeWayMatch.MatchingStatus.MATCHED

    def test_integrity_checkers_and_seed(self):
        call_command("seed_purchasing_inventory_demo")
        call_command("check_procurement_integrity")
        call_command("check_inventory_integrity")
        call_command("check_transfer_integrity")
