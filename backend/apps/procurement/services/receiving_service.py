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


class GoodsReceivingService:
    """Document-oriented receiving, for callers that hold a GRN rather than a scan session.

    The scan-based flow in ReceivingService is the operational one -- a receiver
    at a bay with a barcode gun. This is the same domain reached from the other
    direction: a GRN opened against a purchase order, with batches captured and
    released against its lines. Both post to the same receipt.
    """

    @staticmethod
    @transaction.atomic
    def start_goods_receipt(*, tenant, grn_number, purchase_order, receiving_branch,
                            receiver, delivery_note_number, arrival_time=None):
        """Open a receipt against a purchase order.

        The delivery note is unique per supplier: the same note received twice
        is the classic double-receipt, and it books stock that arrived once as
        stock that arrived twice.
        """
        if purchase_order.status not in {
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        }:
            raise ValidationError(
                f"Goods cannot be received against a purchase order in "
                f"{purchase_order.status}."
            )

        duplicate = GoodsReceipt.all_objects.filter(
            tenant=tenant,
            supplier=purchase_order.supplier,
            delivery_note_number=delivery_note_number,
        ).first()
        if duplicate is not None:
            raise ValidationError(
                f"Delivery note {delivery_note_number} has already been received "
                f"on {duplicate.grn_number}."
            )

        return GoodsReceipt.all_objects.create(
            tenant=tenant,
            grn_number=grn_number,
            purchase_order=purchase_order,
            supplier=purchase_order.supplier,
            receiving_branch=receiving_branch,
            received_by=receiver,
            delivery_note_number=delivery_note_number,
            arrival_time=arrival_time or timezone.now(),
            status=GoodsReceipt.Status.DRAFT,
        )

    @staticmethod
    @transaction.atomic
    def capture_batch(*, manufacturer_batch_number, expiry_date, received_quantity,
                      grn_line=None, goods_receipt=None, po_line=None, sku=None,
                      manufacture_date=None):
        """Record a batch against a receipt line.

        Batch and expiry are captured at receipt because they cannot be
        recovered later: once cartons are on a shelf, nobody can tell which
        batch a given pack came from, and a recall then has to quarantine
        everything.

        Received stock is quarantined rather than accepted. Quality release is
        a separate decision by a different person.
        """
        if expiry_date is None:
            raise ValidationError("A batch requires an expiry date.")
        if expiry_date <= timezone.now().date():
            raise ValidationError(
                f"Batch {manufacturer_batch_number} expires on {expiry_date} "
                "and cannot be received."
            )
        if received_quantity <= 0:
            raise ValidationError("A received quantity must be positive.")

        if grn_line is None:
            if goods_receipt is None or po_line is None:
                raise ValidationError(
                    "A batch needs either a receipt line, or a receipt and a "
                    "purchase-order line to attach itself to."
                )
            grn_line, _ = GoodsReceiptLine.all_objects.get_or_create(
                tenant=goods_receipt.tenant,
                goods_receipt=goods_receipt,
                po_line=po_line,
                sku=sku or po_line.sku,
                defaults={"delivered_quantity": 0},
            )
        line = grn_line
        sku = sku or line.sku

        batch = ReceivedBatch.all_objects.create(
            tenant=line.tenant,
            grn_line=line,
            sku=sku,
            manufacturer_batch_number=manufacturer_batch_number,
            manufacture_date=manufacture_date,
            expiry_date=expiry_date,
            received_quantity=received_quantity,
            # Nothing is accepted on arrival.
            quarantined_quantity=received_quantity,
        )

        line.delivered_quantity = (line.delivered_quantity or 0) + received_quantity
        line.quarantined_quantity = (line.quarantined_quantity or 0) + received_quantity
        line.save(update_fields=["delivered_quantity", "quarantined_quantity", "updated_at"])

        receipt = line.goods_receipt
        receipt.status = GoodsReceipt.Status.PENDING_INSPECTION
        receipt.save(update_fields=["status", "updated_at"])
        return batch

    @staticmethod
    @transaction.atomic
    def release_batch(*, batch, released_by=None, actor=None, reason="", quantity=None):
        """Move quarantined stock to accepted.

        Refuses to release more than is quarantined -- releasing stock that was
        never received is how a receipt starts disagreeing with the shelf.
        """
        # Callers name this actor or released_by depending on which workflow
        # they came from; either identifies the person, which is what matters.
        releaser = released_by or actor
        if releaser is None:
            raise ValidationError("Quality release requires a named releaser.")

        quantity = batch.quarantined_quantity if quantity is None else quantity
        if quantity <= 0:
            raise ValidationError("A release quantity must be positive.")
        if quantity > batch.quarantined_quantity:
            raise ValidationError(
                f"Cannot release {quantity}; only {batch.quarantined_quantity} "
                "is quarantined on this batch."
            )

        batch.quarantined_quantity -= quantity
        batch.accepted_quantity = (batch.accepted_quantity or 0) + quantity
        batch.save(update_fields=["quarantined_quantity", "accepted_quantity", "updated_at"])

        line = batch.grn_line
        line.quarantined_quantity = max(0, (line.quarantined_quantity or 0) - quantity)
        line.accepted_quantity = (line.accepted_quantity or 0) + quantity
        line.save(update_fields=["quarantined_quantity", "accepted_quantity", "updated_at"])
        return batch
