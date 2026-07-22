import decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location, Organization
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierReturn,
    ThreeWayMatch,
)
from apps.tenancy.models import Tenant

User = get_user_model()


class Command(BaseCommand):
    help = "Seed deterministic enterprise procurement & goods receiving data."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding enterprise procurement data...")

        tenant, _ = Tenant.objects.get_or_create(slug="default", defaults={"name": "Default Tenant"})
        user, _ = User.objects.get_or_create(
            username="seedprocurementuser",
            defaults={"email": "seed_procurement@dawatrace.com", "tenant": tenant},
        )
        org, _ = Organization.all_objects.get_or_create(
            tenant=tenant, code="ORG-MAIN", defaults={"name": "Main Pharmacy Organization"}
        )
        location, _ = Location.all_objects.get_or_create(
            tenant=tenant, code="LOC-MAIN", defaults={"organization": org, "name": "Main Hospital Pharmacy Branch"}
        )

        # 1. Suppliers (15)
        suppliers_data = [
            ("SUP-GSK-001", "GlaxoSmithKline Kenya Ltd", "GSK Kenya", "REG-001", "P0011223344", "APPROVED"),
            ("SUP-PFI-002", "Pfizer Pharmaceuticals East Africa", "Pfizer EA", "REG-002", "P0022334455", "APPROVED"),
            ("SUP-NOV-003", "Novartis Pharma Kenya", "Novartis", "REG-003", "P0033445566", "APPROVED"),
            ("SUP-DAW-004", "Dawa Limited Commercial Dist", "Dawa Supply", "REG-004", "P0044556677", "ACTIVE"),
            ("SUP-SUN-005", "Sun Pharma Distribution Kenya", "Sun Pharma", "REG-005", "P0055667788", "APPROVED"),
            ("SUP-CIP-006", "Cipla Kenya Ltd", "Cipla", "REG-006", "P0066778899", "ACTIVE"),
            ("SUP-BAY-007", "Bayer Healthcare EA", "Bayer", "REG-007", "P0077889900", "APPROVED"),
            ("SUP-AZ-008", "AstraZeneca East Africa", "AstraZeneca", "REG-008", "P0088990011", "APPROVED"),
            ("SUP-SAN-009", "Sanofi Aventis Kenya", "Sanofi", "REG-009", "P0099001122", "APPROVED"),
            ("SUP-TEV-010", "Teva Pharma EA Ltd", "Teva EA", "REG-010", "P0100112233", "UNDER_REVIEW"),
            ("SUP-MED-011", "Mediserve Healthcare Wholesalers", "Mediserve", "REG-011", "P0111223344", "APPROVED"),
            ("SUP-PHA-012", "Pharmachem Kenya Distributors", "Pharmachem", "REG-012", "P0122334455", "SUSPENDED"),
            ("SUP-GLO-013", "Global Health Logistics Ltd", "GlobalHealth", "REG-013", "P0133445566", "PROSPECTIVE"),
            ("SUP-ALT-014", "Altair BioPharma Kenya", "Altair", "REG-014", "P0144556677", "APPROVED"),
            ("SUP-APEX-015", "Apex Medical Supplies Ltd", "Apex Medical", "REG-015", "P0155667788", "APPROVED"),
        ]

        suppliers = {}
        for code, legal, trading, reg, tax, st in suppliers_data:
            sup, _ = Supplier.all_objects.get_or_create(
                tenant=tenant,
                supplier_code=code,
                defaults={
                    "legal_name": legal,
                    "trading_name": trading,
                    "registration_number": reg,
                    "tax_identifier": tax,
                    "status": st,
                    "risk_category": "LOW" if st in ["APPROVED", "ACTIVE"] else "MEDIUM",
                },
            )
            suppliers[code] = sup

            # Add qualification
            SupplierQualification.all_objects.get_or_create(
                tenant=tenant,
                supplier=sup,
                qualification_type="WHOLESALE_DEALER_LICENCE",
                licence_number=f"LIC-{code}",
                defaults={
                    "issuing_authority": "Pharmacy and Poisons Board Kenya",
                    "effective_date": date(2025, 1, 1),
                    "expiry_date": date(2027, 12, 31),
                    "verification_status": "VERIFIED" if st in ["APPROVED", "ACTIVE"] else "PENDING",
                },
            )

        # 2. Supplier Product Agreements (30)
        skus = list(CommercialSKU.all_objects.filter(tenant=tenant))
        if skus:
            for idx in range(30):
                sku_item = skus[idx % len(skus)]
                sup_code = suppliers_data[idx % len(suppliers_data)][0]
                sup_obj = suppliers[sup_code]

                SupplierProductAgreement.all_objects.get_or_create(
                    tenant=tenant,
                    supplier=sup_obj,
                    sku=sku_item,
                    defaults={
                        "agreed_unit_price": decimal.Decimal(f"{150 + (idx * 10)}.00"),
                        "minimum_order_quantity": 5,
                        "lead_time_days": 2,
                        "status": "ACTIVE",
                    },
                )

        # 3. Purchase Requisitions (20)
        requisitions = []
        for r_idx in range(1, 21):
            req, _ = PurchaseRequisition.all_objects.get_or_create(
                tenant=tenant,
                requisition_number=f"REQ-2026-{r_idx:03d}",
                defaults={
                    "requesting_branch": location,
                    "requester": user,
                    "requested_delivery_date": date.today() + timedelta(days=7),
                    "priority": "URGENT" if r_idx % 4 == 0 else "NORMAL",
                    "status": "APPROVED" if r_idx <= 15 else "DRAFT",
                },
            )
            requisitions.append(req)

            if skus:
                PurchaseRequisitionLine.all_objects.get_or_create(
                    tenant=tenant,
                    requisition=req,
                    sku=skus[r_idx % len(skus)],
                    defaults={"requested_quantity": 50, "approved_quantity": 50, "outstanding_quantity": 50},
                )

        # 4. Purchase Orders (15)
        purchase_orders = []
        for p_idx in range(1, 16):
            sup_code = suppliers_data[p_idx % len(suppliers_data)][0]
            po, _ = PurchaseOrder.all_objects.get_or_create(
                tenant=tenant,
                po_number=f"PO-2026-{p_idx:03d}",
                defaults={
                    "supplier": suppliers[sup_code],
                    "originating_requisition": requisitions[p_idx - 1] if p_idx <= len(requisitions) else None,
                    "ordering_branch": location,
                    "order_date": date.today() - timedelta(days=5),
                    "expected_delivery_date": date.today() + timedelta(days=2),
                    "total_net": decimal.Decimal("5000.00"),
                    "total_gross": decimal.Decimal("5000.00"),
                    "status": "APPROVED" if p_idx <= 10 else "SENT",
                },
            )
            purchase_orders.append(po)

            if skus:
                PurchaseOrderLine.all_objects.get_or_create(
                    tenant=tenant,
                    purchase_order=po,
                    sku=skus[p_idx % len(skus)],
                    defaults={
                        "ordered_quantity": 100,
                        "received_quantity": 100 if p_idx <= 5 else 0,
                        "unit_price": decimal.Decimal("50.00"),
                        "total_price": decimal.Decimal("5000.00"),
                    },
                )

        # 5. Goods Receipts (10)
        for g_idx in range(1, 11):
            po_item = purchase_orders[g_idx - 1]
            grn, _ = GoodsReceipt.all_objects.get_or_create(
                tenant=tenant,
                grn_number=f"GRN-2026-{g_idx:03d}",
                defaults={
                    "purchase_order": po_item,
                    "supplier": po_item.supplier,
                    "receiving_branch": location,
                    "received_by": user,
                    "delivery_note_number": f"DN-{g_idx:04d}",
                    "arrival_time": timezone.now(),
                    "status": "ACCEPTED" if g_idx <= 8 else "RECEIVING",
                },
            )

            po_line = po_item.lines.first()
            if po_line:
                grn_line, _ = GoodsReceiptLine.all_objects.get_or_create(
                    tenant=tenant,
                    goods_receipt=grn,
                    po_line=po_line,
                    sku=po_line.sku,
                    defaults={
                        "delivered_quantity": 100,
                        "accepted_quantity": 100 if g_idx <= 7 else 80,
                        "quarantined_quantity": 0 if g_idx <= 7 else 20,
                    },
                )

                # Batch capture
                batch, _ = ReceivedBatch.all_objects.get_or_create(
                    tenant=tenant,
                    grn_line=grn_line,
                    manufacturer_batch_number=f"BATCH-2026-{g_idx:03d}",
                    defaults={
                        "sku": grn_line.sku,
                        "expiry_date": date.today() + timedelta(days=365),
                        "received_quantity": 100,
                        "accepted_quantity": 100 if g_idx <= 7 else 80,
                        "quarantined_quantity": 0 if g_idx <= 7 else 20,
                        "quality_status": "RELEASED" if g_idx <= 7 else "QUARANTINED",
                    },
                )

                # Inspection
                ReceivingInspection.all_objects.get_or_create(
                    tenant=tenant,
                    goods_receipt=grn,
                    defaults={
                        "inspector": user,
                        "decision": "RELEASE" if g_idx <= 7 else "QUARANTINE",
                        "reason": "Routine quality release" if g_idx <= 7 else "Temperature check required",
                    },
                )

                # 3-Way match
                ThreeWayMatch.all_objects.get_or_create(
                    tenant=tenant,
                    purchase_order=po_item,
                    goods_receipt=grn,
                    defaults={"invoice_reference": f"INV-SUP-{g_idx:03d}", "matching_status": "MATCHED"},
                )

        # 6. Supplier Returns (1)
        if purchase_orders:
            grn_item = GoodsReceipt.all_objects.filter(tenant=tenant).first()
            if grn_item:
                SupplierReturn.all_objects.get_or_create(
                    tenant=tenant,
                    return_number="RET-2026-001",
                    defaults={
                        "goods_receipt": grn_item,
                        "supplier": grn_item.supplier,
                        "reason": "Damaged outer packaging during transit",
                        "status": "APPROVED",
                    },
                )

        self.stdout.write(self.style.SUCCESS("✅ Enterprise procurement data seeded successfully!"))
