from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
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
from apps.procurement.models import Supplier
from apps.procurement.services import ProcurementService, QualityService, ReceivingService, ThreeWayMatchService
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Seed idempotent purchasing, receiving, inventory and warehouse demo scenarios."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Purchasing, Receiving & Inventory Demo Data...")

        tenant, _ = Tenant.objects.get_or_create(
            slug="tiba-demo",
            defaults={"name": "TibaTrace Demo Tenant", "status": Tenant.STATUS_ACTIVE}
        )

        org, _ = Organization.all_objects.get_or_create(
            tenant=tenant,
            code="TIBA-HQ",
            defaults={"name": "TibaTrace Health HQ", "status": "ACTIVE"}
        )

        branch1, _ = Location.all_objects.get_or_create(
            tenant=tenant,
            code="ELD-MAIN",
            defaults={"organization": org, "name": "Eldoret Main Dispensary", "location_type": "BRANCH", "status": "ACTIVE"}
        )

        branch2, _ = Location.all_objects.get_or_create(
            tenant=tenant,
            code="KSM-BRANCH",
            defaults={"organization": org, "name": "Kisumu Outpatient Pharmacy", "location_type": "BRANCH", "status": "ACTIVE"}
        )

        receiver, _ = User.objects.get_or_create(
            username="demo-receiver", defaults={"tenant": tenant}
        )
        inspector, _ = User.objects.get_or_create(
            username="demo-inspector", defaults={"tenant": tenant}
        )

        substance, _ = ActiveSubstance.all_objects.get_or_create(
            code="SUB-AMOX",
            defaults={"is_global": True, "canonical_name": "Amoxicillin", "display_name": "Amoxicillin", "search_name": "amoxicillin"}
        )

        form, _ = DoseForm.objects.get_or_create(
            name="Oral Capsule",
            defaults={"code": "CAP"}
        )

        pack, _ = PackageDefinition.objects.get_or_create(
            code="PACK-CAP-100",
            defaults={
                "description": "100 Capsules",
                "unit_of_measure": "pack",
                "quantity_in_parent": 100,
            }
        )

        # A SKU does not carry a strength or a dose form. It reaches them through
        # the manufactured product and its clinical product, so the intermediate
        # layers have to exist before the pack can.
        clinical, _ = ClinicalMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code="CMP-AMOX-500",
            defaults={"canonical_name": "Amoxicillin 500mg", "dose_form": form}
        )
        IngredientComposition.objects.get_or_create(
            clinical_product=clinical,
            active_substance=substance,
            defaults={"numerator_value": Decimal("500"), "numerator_unit": "mg"}
        )
        manufactured, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code="MP-AMOX-500",
            defaults={"brand_name": "Amoxil 500mg", "clinical_product": clinical}
        )

        sku, _ = CommercialSKU.all_objects.get_or_create(
            tenant=tenant,
            sku_code="SKU-AMOX-500",
            defaults={
                "display_name": "Amoxil 500mg x100",
                "manufactured_product": manufactured,
                "package_definition": pack,
            }
        )

        supplier, _ = Supplier.all_objects.get_or_create(
            tenant=tenant,
            supplier_code="SUP-MED-001",
            defaults={
                "legal_name": "MedPharma Distributors Kenya Ltd",
                "status": Supplier.Status.APPROVED,
                "country": "Kenya",
            }
        )

        loc1, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch1,
            location_code="MAIN-BAY-1",
            defaults={
                "name": "Main Receiving Bay 1",
                "location_type": InventoryLocation.LocationType.RECEIVING,
                # Deliveries land quarantined until inspection releases them.
                "quarantine_capability": True,
            }
        )

        loc2, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch2,
            location_code="KSM-DISP-1",
            defaults={"name": "Kisumu Shelf A1", "location_type": InventoryLocation.LocationType.DISPENSARY}
        )

        po = ProcurementService.create_purchase_order(
            tenant=tenant,
            supplier=supplier,
            ordering_branch=branch1,
            lines_data=[{"sku": sku, "quantity": 100, "unit_cost": Decimal("250.00")}],
            created_by=None,
        )
        ProcurementService.approve_purchase_order(purchase_order=po, approver=None)
        # Goods cannot be received against an order the supplier never got.
        ProcurementService.send_po(purchase_order=po)

        session = ReceivingService.open_receiving_session(
            tenant=tenant,
            purchase_order=po,
            branch=branch1,
            delivery_note_number="DN-99881",
            received_by=None,
        )

        ReceivingService.record_scan(
            session=session,
            sku=sku,
            scanned_barcode="6001234567890",
            batch_number="BAT-AMX-2026",
            expiry_date=timezone.localdate() + timedelta(days=365),
            scanned_quantity=100,
        )

        grn = ReceivingService.post_goods_receipt_note(
            session=session,
            destination_location=loc1,
            actor=receiver,
        )

        QualityService.record_inspection(
            goods_receipt=grn,
            inspector=inspector,
            decision="RELEASE",
            reason="Seals intact, quantities and expiry dates match the delivery note.",
            temperature_excursion=False,
            notes="Passed quality check",
        )

        ThreeWayMatchService.perform_three_way_match(
            purchase_order=po,
            goods_receipt=grn,
            invoice_reference="INV-SUP-99881",
            invoice_amount=Decimal("25000.00"),
        )

        self.stdout.write(self.style.SUCCESS("SEED_PURCHASING_INVENTORY_DEMO_COMPLETE"))
