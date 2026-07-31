import logging
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.tenant_context import set_current_tenant_id
from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress
from apps.inventory.models import InventoryBatch, InventoryLocation
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.sales.models import (
    CustomerPriceAgreement,
    DeliveryLine,
    DeliveryRecord,
    DispatchLine,
    DispatchOrder,
    Package,
    PackageLine,
    PackingSession,
    PickingTask,
    PickingWave,
    PriceList,
    PriceListEntry,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderAllocation,
    SalesOrderLine,
    SalesReturnAuthorization,
    SalesReturnLine,
)
from apps.tenancy.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Idempotently seed deterministic sample sales data"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, default="tenant-a", help="Tenant slug")

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_slug = options["tenant"]
        tenant, _ = Tenant.objects.get_or_create(slug=tenant_slug, defaults={"name": f"Tenant {tenant_slug}"})
        set_current_tenant_id(tenant.pk)
        self.stdout.write(f"Seeding sales data for tenant: {tenant.name}")

        now = timezone.now()
        next_month = now + timedelta(days=30)
        next_year = now + timedelta(days=365)

        # 1. Base Data (Medicines & Inventory)
        dose_form, _ = DoseForm.objects.get_or_create(code="DF-TABLET", defaults={"name": "Tablet"})
        cmp, _ = ClinicalMedicinalProduct.objects.get_or_create(
            tenant=tenant,
            code="CMP-PARA-500",
            defaults={"canonical_name": "Paracetamol 500mg Tablet", "dose_form": dose_form, "status": "ACTIVE"},
        )
        mmp, _ = ManufacturedMedicinalProduct.objects.get_or_create(
            tenant=tenant,
            code="MMP-PARA-500",
            defaults={"brand_name": "ParaMax 500mg", "clinical_product": cmp, "status": "ACTIVE"},
        )
        pack_def, _ = PackageDefinition.objects.get_or_create(
            code="PACK-100",
            defaults={"description": "Pack of 100", "unit_of_measure": "PIECES", "quantity_in_parent": 100},
        )

        sku1, _ = CommercialSKU.objects.get_or_create(
            tenant=tenant,
            sku_code="SKU-PARA-500",
            defaults={
                "display_name": "Paracetamol 500mg Pack of 100",
                "manufactured_product": mmp,
                "package_definition": pack_def,
            },
        )
        sku2, _ = CommercialSKU.objects.get_or_create(
            tenant=tenant,
            sku_code="SKU-AMOXI-250",
            defaults={
                "display_name": "Amoxicillin 250mg Pack of 50",
                "manufactured_product": mmp,
                "package_definition": pack_def,
            },
        )
        # Organizations
        from apps.organizations.models import Location, Organization

        org, _ = Organization.objects.get_or_create(
            tenant=tenant, code="ORG-MAIN", defaults={"name": "Main Organization", "organization_type": "PHARMACY"}
        )
        branch, _ = Location.objects.get_or_create(
            tenant=tenant,
            code="BR-MAIN-01",
            defaults={"organization": org, "name": "Main Branch", "location_type": "WAREHOUSE"},
        )

        loc, _ = InventoryLocation.objects.get_or_create(
            tenant=tenant,
            location_code="LOC-MAIN-01",
            defaults={"name": "Main Warehouse A1", "branch": branch, "location_type": "WAREHOUSE"},
        )

        batch1, _ = InventoryBatch.objects.get_or_create(
            tenant=tenant,
            manufacturer_batch_number="B-PARA-001",
            defaults={
                "sku": sku1,
                "manufactured_product": mmp,
                "expiry_date": next_year.date(),
                "quality_status": "RELEASED",
            },
        )
        batch2, _ = InventoryBatch.objects.get_or_create(
            tenant=tenant,
            manufacturer_batch_number="B-AMOXI-001",
            defaults={
                "sku": sku2,
                "manufactured_product": mmp,
                "expiry_date": next_year.date(),
                "quality_status": "RELEASED",
            },
        )

        # 2. Customers
        customer_data = [
            ("CUST-PHARMA", "City Pharmacy", "PHARMACY"),
            ("CUST-HOSP", "General Hospital", "HOSPITAL"),
            ("CUST-DIST", "Regional Distro", "DISTRIBUTOR"),
        ]

        customers = {}
        for code, name, ctype in customer_data:
            cust, _ = Customer.objects.get_or_create(
                tenant=tenant,
                customer_number=code,
                defaults={"legal_name": name, "customer_type": ctype, "status": "ACTIVE"},
            )
            customers[code] = cust

            CustomerCommercialProfile.objects.get_or_create(
                tenant=tenant, customer=cust, defaults={"credit_limit": Decimal("100000.00"), "payment_terms": "NET30"}
            )

            CustomerDeliveryAddress.objects.get_or_create(
                tenant=tenant,
                customer=cust,
                address_line1="123 Main St",
                address_code="ADDR-1",
                defaults={"city": "Nairobi", "is_active": True, "recipient_name": name},
            )

        pharma_cust = customers["CUST-PHARMA"]

        # 3. Pricing
        plist, _ = PriceList.objects.get_or_create(
            tenant=tenant,
            code="PL-RETAIL-2024",
            defaults={
                "name": "Retail Price List 2024",
                "currency": "KES",
                "status": "ACTIVE",
                "effective_from": now.date(),
            },
        )
        PriceListEntry.objects.get_or_create(
            tenant=tenant,
            price_list=plist,
            sku=sku1,
            effective_from=now.date(),
            defaults={"unit_price": Decimal("150.00")},
        )
        PriceListEntry.objects.get_or_create(
            tenant=tenant,
            price_list=plist,
            sku=sku2,
            effective_from=now.date(),
            defaults={"unit_price": Decimal("250.00")},
        )

        CustomerPriceAgreement.objects.get_or_create(
            tenant=tenant,
            customer=pharma_cust,
            sku=sku1,
            effective_from=now.date(),
            defaults={
                "agreed_price": Decimal("135.00"),
                "discount_percentage": Decimal("10.00"),
                "is_active": True,
                "effective_to": next_year.date(),
            },
        )

        # 4. Quotations
        quotation, _ = Quotation.objects.get_or_create(
            tenant=tenant,
            quotation_number="QT-2024-001",
            defaults={
                "branch": branch,
                "customer": pharma_cust,
                "status": "ACCEPTED",
                "valid_until": next_month.date(),
            },
        )
        if not QuotationLine.objects.filter(quotation=quotation).exists():
            QuotationLine.objects.create(
                tenant=tenant,
                quotation=quotation,
                sku=sku1,
                requested_quantity=Decimal("10.00"),
                unit="PACK",
                base_unit_price=Decimal("150.00"),
                agreed_unit_price=Decimal("150.00"),
                line_subtotal=Decimal("1500.00"),
                line_total=Decimal("1500.00"),
            )

        # 5. Sales Orders (Various states)
        so_data = [
            ("SO-DRAFT", "DRAFT"),
            ("SO-SUBMITTED", "SUBMITTED"),
            ("SO-APPROVED", "APPROVED"),
            ("SO-RESERVED", "RESERVED"),
            ("SO-ALLOCATED", "ALLOCATED"),
            ("SO-PICKED", "PICKED"),
            ("SO-PACKED", "PACKED"),
            ("SO-DISPATCHED", "DISPATCHED"),
            ("SO-DELIVERED", "DELIVERED"),
            ("SO-RETURNED", "DELIVERED"),  # Returned usually applies to delivered SOs
        ]

        sales_orders = {}
        for num, status in so_data:
            so, created = SalesOrder.objects.get_or_create(
                tenant=tenant,
                order_number=num,
                defaults={"branch": branch, "customer": pharma_cust, "status": status, "currency": "KES"},
            )
            sales_orders[num] = so
            if created:
                so_line = SalesOrderLine.objects.create(
                    tenant=tenant,
                    sales_order=so,
                    sku=sku1,
                    requested_quantity=Decimal("10.0000"),
                    unit="PACK",
                    base_unit_price=Decimal("150.00"),
                    agreed_unit_price=Decimal("150.00"),
                    line_subtotal=Decimal("1500.00"),
                    line_total=Decimal("1500.00"),
                )

                # Advance states deterministically based on target status
                states = [
                    "APPROVED",
                    "RESERVED",
                    "ALLOCATED",
                    "PICKED",
                    "PACKED",
                    "DISPATCHED",
                    "DELIVERED",
                    "RETURNED",
                ]

                if status in states + ["SUBMITTED"]:
                    so_line.status = "APPROVED"
                    so_line.approved_quantity = Decimal("10.0000")
                    so_line.save()

                if status in ["RESERVED", "ALLOCATED", "PICKED", "PACKED", "DISPATCHED", "DELIVERED", "RETURNED"]:
                    so_line.reserved_quantity = Decimal("10.0000")
                    so_line.status = "RESERVED"
                    so_line.save()

                if status in ["ALLOCATED", "PICKED", "PACKED", "DISPATCHED", "DELIVERED", "RETURNED"]:
                    so_line.allocated_quantity = Decimal("10.0000")
                    so_line.status = "ALLOCATED"
                    so_line.save()
                    # Create allocation
                    alloc = SalesOrderAllocation.objects.create(
                        tenant=tenant,
                        sales_order_line=so_line,
                        inventory_batch=batch1,
                        location=loc,
                        quantity=Decimal("10.0000"),
                        status="ALLOCATED",
                    )

                if status in ["PICKED", "PACKED", "DISPATCHED", "DELIVERED", "RETURNED"]:
                    so_line.picked_quantity = Decimal("10.0000")
                    so_line.status = "PICKED"
                    so_line.save()

                    wave, _ = PickingWave.objects.get_or_create(
                        tenant=tenant, wave_number=f"WAVE-{num}", defaults={"branch": branch, "status": "COMPLETED"}
                    )
                    PickingTask.objects.create(
                        tenant=tenant,
                        picking_wave=wave,
                        sales_order=so,
                        sales_order_line=so_line,
                        allocation=alloc,
                        source_location=loc,
                        sku=sku1,
                        batch=batch1,
                        requested_quantity=Decimal("10.0000"),
                        picked_quantity=Decimal("10.0000"),
                        status="PICKED",
                    )

                if status in ["PACKED", "DISPATCHED", "DELIVERED", "RETURNED"]:
                    so_line.packed_quantity = Decimal("10.0000")
                    so_line.status = "PACKED"
                    so_line.save()

                    session, _ = PackingSession.objects.get_or_create(
                        tenant=tenant,
                        session_number=f"PACK-{num}",
                        defaults={"branch": branch, "sales_order": so, "status": "CLOSED"},
                    )
                    package, _ = Package.objects.get_or_create(
                        tenant=tenant,
                        packing_session=session,
                        sales_order=so,
                        package_number=f"PKG-{num}",
                        defaults={"package_type": "BOX", "status": "SEALED"},
                    )
                    PackageLine.all_objects.get_or_create(
                        tenant=tenant,
                        package=package,
                        sales_order_line=so_line,
                        defaults={
                            "sku": sku1,
                            "batch": batch1,
                            "quantity": Decimal("10.0000"),
                            "unit": "PACK",
                        },
                    )

                if status in ["DISPATCHED", "DELIVERED", "RETURNED"]:
                    so_line.dispatched_quantity = Decimal("10.0000")
                    so_line.status = "DISPATCHED"
                    so_line.save()

                    dispatch, _ = DispatchOrder.objects.get_or_create(
                        tenant=tenant,
                        dispatch_number=f"DISP-{num}",
                        defaults={
                            "branch": branch,
                            "customer": pharma_cust,
                            "status": "DISPATCHED",
                            "vehicle": "KAA 123A",
                        },
                    )
                    dispatch_key = f"{tenant.slug}-DISP-{num}"
                    dispatch_line = DispatchLine.all_objects.filter(
                        tenant=tenant,
                        idempotency_key=dispatch_key,
                    ).first()
                    if dispatch_line is None:
                        dispatch_line = DispatchLine.all_objects.filter(
                            tenant=tenant,
                            dispatch_order=dispatch,
                            sales_order_line=so_line,
                        ).first()
                    if dispatch_line is None:
                        dispatch_line = DispatchLine.all_objects.create(
                            tenant=tenant,
                            dispatch_order=dispatch,
                            sales_order_line=so_line,
                            sku=sku1,
                            batch=batch1,
                            quantity=Decimal("10.0000"),
                            unit="PACK",
                            idempotency_key=dispatch_key,
                        )

                if status in ["DELIVERED", "RETURNED"]:
                    so_line.delivered_quantity = Decimal("10.0000")
                    so_line.status = "DELIVERED"
                    so_line.save()

                    delivery, _ = DeliveryRecord.objects.get_or_create(
                        tenant=tenant, dispatch_order=dispatch, customer=pharma_cust, defaults={"status": "DELIVERED"}
                    )
                    DeliveryLine.all_objects.get_or_create(
                        tenant=tenant,
                        delivery_record=delivery,
                        dispatch_line=dispatch_line,
                        defaults={
                            "sales_order_line": so_line,
                            "sku": sku1,
                            "batch": batch1,
                            "dispatched_quantity": Decimal("10.0000"),
                            "accepted_quantity": Decimal("10.0000"),
                        },
                    )

                if num == "SO-RETURNED":
                    so_line.returned_quantity = Decimal("5.0000")
                    so_line.save()

                    sra, _ = SalesReturnAuthorization.objects.get_or_create(
                        tenant=tenant,
                        return_number=f"SRA-{num}",
                        defaults={"sales_order": so, "customer": pharma_cust, "status": "APPROVED"},
                    )
                    SalesReturnLine.all_objects.get_or_create(
                        tenant=tenant,
                        return_authorization=sra,
                        sales_order_line=so_line,
                        defaults={
                            "sku": sku1,
                            "batch": batch1,
                            "quantity": Decimal("5.0000"),
                            "received_quantity": Decimal("5.0000"),
                        },
                    )

        self.stdout.write(self.style.SUCCESS("Sales data seeded successfully!"))
