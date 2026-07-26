from __future__ import annotations

import decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import InventoryBatch, InventoryLedgerEntry
from apps.inventory.services import InventoryLedgerService
from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    ReceivedBatch,
    ReceivingScan,
    ReceivingSession,
)


class ReceivingService:
    """
    Authoritative domain service for scan-to-receive operations, receiving sessions,
    tolerance validation, and atomic, ledger-backed GRN posting.
    """

    @staticmethod
    @transaction.atomic
    def open_receiving_session(*, tenant, purchase_order, branch, delivery_note_number, received_by) -> ReceivingSession:
        if purchase_order.status not in [PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.RELEASED, PurchaseOrder.Status.PARTIALLY_RECEIVED]:
            raise ValidationError(f"Cannot receive goods for PO in status {purchase_order.status}")

        session_num = f"RCV-{timezone.now().strftime('%Y%m%d')}-{ReceivingSession.all_objects.filter(tenant=tenant).count() + 1:04d}"
        session = ReceivingSession.all_objects.create(
            tenant=tenant,
            session_number=session_num,
            purchase_order=purchase_order,
            supplier=purchase_order.supplier,
            branch=branch,
            delivery_note_number=delivery_note_number,
            received_by=received_by,
            status="ACTIVE",
        )
        return session

    @staticmethod
    @transaction.atomic
    def record_scan(*, session, sku, scanned_barcode, batch_number, expiry_date, scanned_quantity) -> ReceivingScan:
        if session.status != "ACTIVE":
            raise ValidationError("Cannot record scans on an inactive receiving session.")

        po_lines = session.purchase_order.lines.filter(sku=sku)
        if not po_lines.exists():
            raise ValidationError(f"Item {sku.sku_code} is not included in Purchase Order {session.purchase_order.po_number}.")

        if expiry_date <= timezone.now().date():
            raise ValidationError(f"Scanned batch {batch_number} has already expired.")

        scan = ReceivingScan.all_objects.create(
            tenant=session.tenant,
            session=session,
            sku=sku,
            scanned_barcode=scanned_barcode,
            batch_number=batch_number,
            expiry_date=expiry_date,
            scanned_quantity=scanned_quantity,
        )
        return scan

    @staticmethod
    @transaction.atomic
    def post_goods_receipt_note(*, session, destination_location, actor) -> GoodsReceipt:
        if session.status != "ACTIVE":
            raise ValidationError("Receiving session has already been posted or closed.")

        scans = session.scans.all()
        if not scans.exists():
            raise ValidationError("Cannot post a GRN for a session with no scanned items.")

        grn_number = f"GRN-{timezone.now().strftime('%Y%m%d')}-{GoodsReceipt.all_objects.filter(tenant=session.tenant).count() + 1:05d}"
        goods_receipt = GoodsReceipt.all_objects.create(
            tenant=session.tenant,
            grn_number=grn_number,
            purchase_order=session.purchase_order,
            supplier=session.supplier,
            receiving_branch=session.branch,
            delivery_note_number=session.delivery_note_number,
            receiver=actor,
            arrival_time=timezone.now(),
            status=GoodsReceipt.Status.POSTED,
        )

        for scan in scans:
            po_line = session.purchase_order.lines.get(sku=scan.sku)
            unit_cost = po_line.unit_cost

            ReceivedBatch.all_objects.create(
                tenant=session.tenant,
                goods_receipt=goods_receipt,
                sku=scan.sku,
                manufacturer_batch_number=scan.batch_number,
                expiry_date=scan.expiry_date,
                received_quantity=scan.scanned_quantity,
                accepted_quantity=scan.scanned_quantity,
                unit_cost=unit_cost,
                quality_status=ReceivedBatch.QualityStatus.QUARANTINED,
            )

            GoodsReceiptLine.all_objects.create(
                tenant=session.tenant,
                goods_receipt=goods_receipt,
                po_line=po_line,
                sku=scan.sku,
                received_quantity=scan.scanned_quantity,
                accepted_quantity=scan.scanned_quantity,
                unit_cost=unit_cost,
                line_total=scan.scanned_quantity * unit_cost,
            )

            po_line.received_quantity += scan.scanned_quantity
            po_line.save()

            inv_batch, _ = InventoryBatch.all_objects.get_or_create(
                tenant=session.tenant,
                sku=scan.sku,
                batch_number=scan.batch_number,
                defaults={
                    "expiry_date": scan.expiry_date,
                    "quality_status": "QUARANTINED",
                },
            )

            InventoryLedgerService.post_entry(
                tenant=session.tenant,
                branch=session.branch,
                location=destination_location,
                sku=scan.sku,
                entry_type=InventoryLedgerEntry.EntryType.PURCHASE_RECEIPT,
                quantity_delta=decimal.Decimal(scan.scanned_quantity),
                unit="pack",
                base_quantity_delta=decimal.Decimal(scan.scanned_quantity),
                effective_timestamp=timezone.now(),
                source_document_type="GOODS_RECEIPT",
                source_document_id=str(goods_receipt.id),
                idempotency_key=f"GRN-{goods_receipt.id}-{scan.id}",
                actor=actor,
                inventory_batch=inv_batch,
                notes=f"GRN {grn_number} Receipt",
            )

        session.status = "COMPLETED"
        session.save()

        po = session.purchase_order
        if all(line.received_quantity >= line.ordered_quantity for line in po.lines.all()):
            po.status = PurchaseOrder.Status.FULLY_RECEIVED
        else:
            po.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
        po.save()

        return goods_receipt
