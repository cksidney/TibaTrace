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
    PurchaseOrderLine,
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
        if purchase_order.status not in [PurchaseOrder.Status.SENT, PurchaseOrder.Status.ACKNOWLEDGED, PurchaseOrder.Status.PARTIALLY_RECEIVED]:
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


#: Capability that authorises quality release. Platform administrators hold it
#: implicitly; everybody else must be granted it.
QUALITY_RELEASE_CAPABILITY = "quality.release"


def _may_release_quality(actor) -> bool:
    if getattr(actor, "is_platform_admin", False) or getattr(actor, "is_superuser", False):
        return True
    checker = getattr(actor, "has_capability", None)
    if callable(checker):
        return bool(checker(QUALITY_RELEASE_CAPABILITY))
    return False


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
            # RECEIVING, not DRAFT. Starting a goods receipt means a delivery
            # is on the bay and somebody is counting it; the receipt is already
            # in progress, and DRAFT would suggest a document nobody has begun.
            status=GoodsReceipt.Status.RECEIVING,
        )

    @staticmethod
    @transaction.atomic
    def receive_line(*, goods_receipt, po_line, delivered_quantity, accepted_quantity=0,
                     quarantined_quantity=0, rejected_quantity=0, discrepancy_reason="",
                     sku=None, idempotency_key=""):
        """Record what arrived against a purchase-order line, and its disposition.

        Accepted defaults to zero. Goods are delivered first and accepted only
        after inspection, and a default that accepted everything on arrival
        would make the quality step decorative.

        Every delivered unit must end up in exactly one of accepted, quarantined
        or rejected, and the three together may not exceed what arrived.
        Disposition adding to more than the delivery means stock has been
        conjured somewhere between the bay and the ledger.
        """
        if delivered_quantity is None or delivered_quantity < 0:
            raise ValidationError("A delivered quantity cannot be negative.")

        for label, value in (
            ("accepted", accepted_quantity),
            ("quarantined", quarantined_quantity),
            ("rejected", rejected_quantity),
        ):
            if value < 0:
                raise ValidationError(f"A {label} quantity cannot be negative.")

        disposed = accepted_quantity + quarantined_quantity + rejected_quantity
        if disposed > delivered_quantity:
            raise ValidationError(
                f"Disposition exceeds the delivery: {accepted_quantity} accepted plus "
                f"{quarantined_quantity} quarantined plus {rejected_quantity} rejected "
                f"is {disposed}, against {delivered_quantity} delivered."
            )
        if rejected_quantity and not str(discrepancy_reason or "").strip():
            # Rejected stock is a claim against the supplier. Without a reason
            # it cannot be argued, credited, or learned from.
            raise ValidationError("A rejected quantity requires a discrepancy reason.")

        # Lock the purchase-order line for the duration of this receipt. Two
        # receivers working the same delivery would otherwise each read the
        # same received quantity, each find room under the ordered quantity,
        # and both post -- which is how a hundred-unit order becomes a
        # hundred-and-eighty-unit receipt.
        locked_po_line = PurchaseOrderLine.objects.select_for_update().get(pk=po_line.pk)

        already_received = locked_po_line.received_quantity or 0
        if already_received + delivered_quantity > locked_po_line.ordered_quantity:
            raise ValidationError(
                f"Total received quantity cannot exceed ordered quantity: "
                f"{already_received} already received plus {delivered_quantity} "
                f"exceeds the {locked_po_line.ordered_quantity} ordered."
            )

        if idempotency_key:
            # A retry over poor connectivity must not receive the same goods
            # twice. The key is unique per tenant, so the second call returns
            # the first call's line rather than adding to it.
            existing = GoodsReceiptLine.all_objects.filter(
                tenant=goods_receipt.tenant, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                return existing

        line, _ = GoodsReceiptLine.all_objects.get_or_create(
            tenant=goods_receipt.tenant,
            goods_receipt=goods_receipt,
            po_line=po_line,
            sku=sku or po_line.sku,
            defaults={"delivered_quantity": 0, "idempotency_key": idempotency_key},
        )
        line.delivered_quantity = (line.delivered_quantity or 0) + delivered_quantity
        line.accepted_quantity = (line.accepted_quantity or 0) + accepted_quantity
        line.quarantined_quantity = (line.quarantined_quantity or 0) + quarantined_quantity
        line.rejected_quantity = (line.rejected_quantity or 0) + rejected_quantity
        if discrepancy_reason:
            line.discrepancy_reason = discrepancy_reason
        if idempotency_key and not line.idempotency_key:
            line.idempotency_key = idempotency_key
        line.save(update_fields=[
            "delivered_quantity", "accepted_quantity", "quarantined_quantity",
            "rejected_quantity", "discrepancy_reason", "idempotency_key", "updated_at",
        ])

        # The purchase-order line carries the running total, so the next
        # receipt is measured against everything received so far rather than
        # against this delivery alone.
        locked_po_line.received_quantity = already_received + delivered_quantity
        locked_po_line.save(update_fields=["received_quantity", "updated_at"])

        goods_receipt.status = GoodsReceipt.Status.RECEIVING
        goods_receipt.save(update_fields=["status", "updated_at"])
        return line

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
        if manufacture_date and manufacture_date >= expiry_date:
            # A typo, not stock to refuse -- the two need different corrections,
            # so they get different messages.
            raise ValidationError(
                f"Manufacture date must precede expiry date; batch "
                f"{manufacturer_batch_number} is dated {manufacture_date} "
                f"expiring {expiry_date}."
            )
        if manufacture_date and manufacture_date >= expiry_date:
            raise ValidationError(
                f"Manufacture date must precede expiry date; batch "
                f"{manufacturer_batch_number} is dated {manufacture_date} "
                f"expiring {expiry_date}."
            )
        if expiry_date <= timezone.now().date():
            raise ValidationError(
                f"Cannot receive expired batch: {manufacturer_batch_number} "
                f"expires on {expiry_date}."
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
        receipt.status = GoodsReceipt.Status.UNDER_INSPECTION
        receipt.save(update_fields=["status", "updated_at"])
        return batch

    @staticmethod
    @transaction.atomic
    def close_goods_receipt(*, goods_receipt):
        """Close the receipt and settle the purchase order's received state.

        The purchase order is marked fully received only when every line has had
        its ordered quantity delivered. Closing one shipment is not the same as
        completing an order -- a supplier shipping in three deliveries would
        otherwise have the order closed against the first, and the outstanding
        two would stop being chased.
        """
        if goods_receipt.status in {
            GoodsReceipt.Status.ACCEPTED,
            GoodsReceipt.Status.CLOSED,
            GoodsReceipt.Status.CANCELLED,
        }:
            raise ValidationError(
                f"Goods receipt {goods_receipt.grn_number} is already {goods_receipt.status}."
            )

        goods_receipt.status = GoodsReceipt.Status.ACCEPTED
        goods_receipt.save(update_fields=["status", "updated_at"])

        purchase_order = goods_receipt.purchase_order
        lines = list(purchase_order.lines.all())
        if lines and all(
            (line.received_quantity or 0) >= line.ordered_quantity for line in lines
        ):
            purchase_order.status = PurchaseOrder.Status.FULLY_RECEIVED
        else:
            purchase_order.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
        purchase_order.save(update_fields=["status", "updated_at"])

        return goods_receipt

    @staticmethod
    @transaction.atomic
    def release_batch(*, batch, released_by=None, actor=None, reason="", quantity=None):
        """Move quarantined stock into accepted, released stock.

        Authority is checked before anything else. Quality release is the step
        that turns goods nobody has vouched for into goods a pharmacist may
        dispense, and §24 restricts it to authorised quality users -- a
        receiver releasing their own delivery is exactly the separation the
        control exists to enforce.

        Refuses to release more than was received. Releasing stock that never
        arrived is how a receipt starts disagreeing with the shelf.
        """
        # Callers name this actor or released_by depending on which workflow
        # they came from; either identifies the person, which is what matters.
        releaser = released_by or actor
        if releaser is None:
            raise ValidationError("Quality release requires a named releaser.")

        if not _may_release_quality(releaser):
            raise ValidationError(
                "Actor lacks quality-release authority. Quality release is "
                "restricted to authorised quality users."
            )

        already_released = batch.accepted_quantity or 0
        outstanding = (batch.received_quantity or 0) - already_released
        quantity = outstanding if quantity is None else quantity

        if quantity <= 0:
            raise ValidationError(
                f"A release quantity must be positive; batch "
                f"{batch.manufacturer_batch_number} has {outstanding} awaiting release."
            )
        if quantity > outstanding:
            raise ValidationError(
                f"Cannot release {quantity}; only {outstanding} of batch "
                f"{batch.manufacturer_batch_number} is awaiting release."
            )

        batch.accepted_quantity = already_released + quantity
        batch.quarantined_quantity = max(0, (batch.quarantined_quantity or 0) - quantity)
        # Fully released only when nothing is left awaiting a decision; a
        # part-release leaves the batch quarantined, because the rest still is.
        if batch.accepted_quantity >= (batch.received_quantity or 0):
            batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
        batch.save(update_fields=[
            "accepted_quantity", "quarantined_quantity", "quality_status", "updated_at",
        ])

        line = batch.grn_line
        line.quarantined_quantity = max(0, (line.quarantined_quantity or 0) - quantity)
        line.accepted_quantity = (line.accepted_quantity or 0) + quantity
        line.save(update_fields=["quarantined_quantity", "accepted_quantity", "updated_at"])
        return batch
