from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.identity.models import User
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation, InventoryReservation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingAllocation,
    DispensingEpisode,
    DispensingLine,
    DispensingReservation,
    PosDeviceHealthRecord,
    PosShiftRecord,
    Prescription,
    PrescriptionItem,
)
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Seed demo data for POS Enterprise Dispensing workflow"

    def handle(self, *args, **options):
        self.stdout.write("Seeding POS Enterprise Dispensing Demo Data...")

        tenant, _ = Tenant.objects.get_or_create(name="TibaTrace Demo Pharmacy", slug="tibatrace-demo")
        org, _ = Organization.all_objects.get_or_create(tenant=tenant, code="DEMO-ORG", defaults={"name": "Demo Pharmacy Org"})
        branch, _ = Location.all_objects.get_or_create(tenant=tenant, code="DEMO-BR", defaults={"organization": org, "name": "Main Dispensary"})
        wh, _ = InventoryLocation.all_objects.get_or_create(tenant=tenant, branch=branch, location_code="DEMO-WH", defaults={"name": "Pharmacy Store"})

        rph, _ = User.objects.get_or_create(username="demo_rph")
        rph.tenant = tenant
        rph.save()
        cashier, _ = User.objects.get_or_create(username="demo_cashier")
        cashier.tenant = tenant
        cashier.save()

        patient, _ = Patient.all_objects.get_or_create(
            tenant=tenant,
            patient_number="DEMO-PAT-1",
            defaults={
                "internal_reference_id": "PAT-REF-001",
                "last_name": "Kamau",
                "first_name": "Grace",
                "sex": "FEMALE",
                "date_of_birth": date(1985, 5, 12),
            },
        )

        practitioner, _ = Practitioner.all_objects.get_or_create(
            tenant=tenant,
            registration_number="A12345",
            defaults={
                "last_name": "Ochieng",
                "first_name": "David",
                "profession": "DOCTOR",
            },
        )

        dose_form, _ = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})
        substance, _ = ActiveSubstance.all_objects.get_or_create(
            tenant=tenant, code="SUB-AMO", defaults={"canonical_name": "Amoxicillin", "display_name": "Amoxicillin", "search_name": "amoxicillin"}
        )
        cmp, _ = ClinicalMedicinalProduct.all_objects.get_or_create(tenant=tenant, code="CMP-AMO-500", defaults={"canonical_name": "Amoxicillin 500mg", "dose_form": dose_form})
        mmp, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(tenant=tenant, code="MMP-AMO-500", defaults={"brand_name": "Amoxil 500mg", "clinical_product": cmp})
        pkg, _ = PackageDefinition.objects.get_or_create(code="PACK-AMO", defaults={"description": "Box of 20", "unit_of_measure": "CAPSULE", "is_dispensing_unit": True})
        sku, _ = CommercialSKU.all_objects.get_or_create(tenant=tenant, sku_code="SKU-AMOX-500", defaults={"display_name": "Amoxil 500mg Caps 20s", "manufactured_product": mmp, "package_definition": pkg})

        batch, _ = InventoryBatch.all_objects.get_or_create(
            tenant=tenant,
            manufactured_product=mmp,
            manufacturer_batch_number="DEMO-BATCH-01",
            defaults={"sku": sku, "expiry_date": date(2028, 10, 31), "quality_status": "RELEASED"},
        )

        InventoryLedgerService.post_entry(
            tenant=tenant,
            branch=branch,
            location=wh,
            sku=sku,
            inventory_batch=batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
            quantity_delta=Decimal("500"),
            unit="CAPSULE",
            base_quantity_delta=Decimal("500"),
            effective_timestamp=timezone.now(),
            source_document_type="DemoReceipt",
            source_document_id="DEMO-REC-01",
            idempotency_key="DEMO-LEDGER-KEY-01",
            actor=rph,
        )

        rx, _ = Prescription.all_objects.get_or_create(
            tenant=tenant,
            prescription_number="DEMO-RX-8001",
            defaults={
                "patient": patient,
                "practitioner": practitioner,
                "organization": org,
                "location": branch,
                "status": "READY_FOR_DISPENSING",
            },
        )

        rx_item, _ = PrescriptionItem.all_objects.get_or_create(
            tenant=tenant,
            prescription=rx,
            defaults={
                "prescribed_sku": sku,
                "medication_name": sku.display_name,
                "dosage_instruction": "Take 1 capsule 3 times a day for 7 days",
                "quantity": Decimal("21"),
            },
        )

        episode, _ = DispensingEpisode.all_objects.get_or_create(
            tenant=tenant,
            dispensing_number="DEMO-DISP-8001",
            defaults={
                "prescription": rx,
                "patient": patient,
                "branch": branch,
                "pharmacy_location": wh,
                "pharmacist": rph,
                "status": "PREPARING",
                "idempotency_key": "DEMO-EPISODE-KEY-01",
            },
        )

        inv_res, _ = InventoryReservation.all_objects.get_or_create(
            tenant=tenant,
            idempotency_key="DEMO-INV-RES-01",
            defaults={
                "branch": branch,
                "source_location": wh,
                "sku": sku,
                "requested_quantity": Decimal("21"),
                "unit": "CAPSULE",
                "purpose": "DEMO_DISPENSING",
            },
        )

        res, _ = DispensingReservation.all_objects.get_or_create(
            tenant=tenant,
            idempotency_key="DEMO-DISP-RES-01",
            defaults={
                "episode": episode,
                "prescription_item": rx_item,
                "inventory_reservation": inv_res,
                "quantity": Decimal("21"),
            },
        )

        alloc, _ = DispensingAllocation.all_objects.get_or_create(
            reservation=res,
            inventory_batch=batch,
            location=wh,
            defaults={
                "tenant": tenant,
                "episode": episode,
                "prescription_item": rx_item,
                "quantity": Decimal("21"),
            },
        )

        DispensingLine.all_objects.get_or_create(
            episode=episode,
            inventory_allocation=alloc,
            defaults={
                "tenant": tenant,
                "prescription_item": rx_item,
                "prescribed_sku": sku,
                "supplied_sku": sku,
                "inventory_batch": batch,
                "quantity_authorized": Decimal("21"),
                "quantity_prepared": Decimal("21"),
                "quantity_supplied": Decimal("0"),
                "unit": "CAPSULE",
                "package_definition": pkg,
                "batch_number_snapshot": "DEMO-BATCH-01",
                "expiry_date_snapshot": date(2028, 10, 31),
                "dosage_label_instructions": "Take 1 capsule 3 times a day for 7 days",
                "status": "PREPARED",
                "prepared_by": rph,
            },
        )

        PosShiftRecord.all_objects.get_or_create(
            tenant=tenant,
            shift_number="DEMO-SHIFT-01",
            defaults={
                "cashier": cashier,
                "pharmacist": rph,
                "location": branch,
                "status": "OPEN",
                "controlled_stock_start_count": 100,
            },
        )

        PosDeviceHealthRecord.all_objects.get_or_create(
            tenant=tenant,
            device_id="DEMO-TERM-01",
            defaults={
                "device_type": "TERMINAL",
                "status": "OK",
                "printer_paper_level": "OK",
                "scanner_connected": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("POS Enterprise Dispensing Demo Data Seeded Successfully."))
