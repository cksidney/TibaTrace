from __future__ import annotations

import decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
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

        # Continued from the highest existing sequence, not a row count. A count
        # reuses a number as soon as any session is removed, and the reused one
        # is already in the audit trail against different goods.
        prefix = f"RCV-{timezone.now().strftime('%Y%m%d')}-"
        last = (
            ReceivingSession.all_objects.filter(
                tenant=tenant, session_number__startswith=prefix
            )
            .order_by("-session_number")
            .values_list("session_number", flat=True)
            .first()
        )
        session_num = f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):04d}"
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

        # Explicit tenant filter rather than `session.purchase_order.lines`.
        # A related manager uses the model's default manager, which here is the
        # tenant-strict one: with no tenant context it returns nothing, and this
        # method then tells the operator the item is not on the order. Scanning a
        # legitimate delivery would read as the wrong goods arriving.
        po_lines = PurchaseOrderLine.all_objects.filter(
            tenant_id=session.tenant_id, purchase_order=session.purchase_order, sku=sku
        )
        if not po_lines.exists():
            raise ValidationError(f"Item {sku.sku_code} is not included in Purchase Order {session.purchase_order.po_number}.")

        if expiry_date <= timezone.localdate():
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

        scans = ReceivingScan.all_objects.filter(
            tenant_id=session.tenant_id, session=session
        )
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
            received_by=actor,
            arrival_time=timezone.now(),
            # RECEIVED, not POSTED: there is no POSTED state on this model, so
            # every GRN posting raised AttributeError here. The goods have
            # arrived and are awaiting inspection, which is what RECEIVED means
            # -- ACCEPTED comes later, from QualityService.
            status=GoodsReceipt.Status.RECEIVED,
        )

        for scan in scans:
            po_line = PurchaseOrderLine.all_objects.get(
                tenant_id=session.tenant_id,
                purchase_order=session.purchase_order,
                sku=scan.sku,
            )
            # The line first: a received batch hangs off the receipt line, not
            # off the receipt.
            grn_line = GoodsReceiptLine.all_objects.create(
                tenant=session.tenant,
                goods_receipt=goods_receipt,
                po_line=po_line,
                sku=scan.sku,
                delivered_quantity=scan.scanned_quantity,
                accepted_quantity=scan.scanned_quantity,
            )

            # No unit cost is copied onto the receipt. Receipt lines carry
            # quantities and the purchase order carries the money, so the price
            # cannot drift between the two and a receipt can never be valued at
            # anything other than what was agreed.
            ReceivedBatch.all_objects.create(
                tenant=session.tenant,
                grn_line=grn_line,
                sku=scan.sku,
                manufacturer_batch_number=scan.batch_number,
                expiry_date=scan.expiry_date,
                received_quantity=scan.scanned_quantity,
                accepted_quantity=scan.scanned_quantity,
                quality_status=ReceivedBatch.QualityStatus.QUARANTINED,
            )

            po_line.received_quantity += scan.scanned_quantity
            po_line.save()

            # Keyed on the batch's real identity, which is the unique
            # constraint on the model: the same manufacturer batch number from
            # the same manufactured product is the same physical batch, whichever
            # SKU packs it. manufactured_product is required and was never set,
            # so this get_or_create could not insert at all.
            inv_batch, _ = InventoryBatch.all_objects.get_or_create(
                tenant=session.tenant,
                manufactured_product=scan.sku.manufactured_product,
                manufacturer_batch_number=scan.batch_number,
                defaults={
                    "sku": scan.sku,
                    "expiry_date": scan.expiry_date,
                    "quality_status": "QUARANTINED",
                },
            )

            InventoryLedgerService.post_entry(
                tenant=session.tenant,
                branch=session.branch,
                location=destination_location,
                sku=scan.sku,
                entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
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
        po_lines = list(
            PurchaseOrderLine.all_objects.filter(tenant_id=po.tenant_id, purchase_order=po)
        )
        # `all()` of an empty sequence is True, so without the emptiness check an
        # order whose lines could not be read would be marked fully received
        # having had nothing verified at all.
        if po_lines and all(
            line.received_quantity >= line.ordered_quantity for line in po_lines
        ):
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
        # all_objects with an explicit tenant filter. `objects` is tenant-strict
        # and returns nothing unless tenant context is set on the thread, so
        # this raised DoesNotExist -- and took the over-receipt guard with it --
        # for every caller outside a request: management commands, Celery tasks,
        # imports.
        locked_po_line = (
            PurchaseOrderLine.all_objects.select_for_update()
            .get(pk=po_line.pk, tenant_id=po_line.tenant_id)
        )

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
        if expiry_date <= timezone.localdate():
            raise ValidationError(
                f"Cannot receive expired batch: {manufacturer_batch_number} "
                f"expires on {expiry_date}."
            )
        if received_quantity <= 0:
            raise ValidationError("A received quantity must be positive.")

        created_line = grn_line is None
        if created_line:
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

        if created_line:
            line.delivered_quantity = (line.delivered_quantity or 0) + received_quantity
            line.quarantined_quantity = (line.quarantined_quantity or 0) + received_quantity
            line.save(update_fields=["delivered_quantity", "quarantined_quantity", "updated_at"])
        else:
            captured = (
                ReceivedBatch.all_objects.filter(
                    tenant_id=line.tenant_id,
                    grn_line=line,
                )
                .exclude(pk=batch.pk)
                .aggregate(total=models.Sum("received_quantity"))["total"]
                or 0
            )
            if captured + received_quantity > line.delivered_quantity:
                raise ValidationError(
                    f"Captured batch quantity exceeds the {line.delivered_quantity} "
                    "units recorded on the receipt line."
                )

        receipt = line.goods_receipt
        receipt.status = GoodsReceipt.Status.UNDER_INSPECTION
        receipt.save(update_fields=["status", "updated_at"])
        return batch

    @staticmethod
    @transaction.atomic
    def receive_batch(
        *,
        goods_receipt,
        po_line,
        manufacturer_batch_number,
        expiry_date,
        received_quantity,
        manufacture_date=None,
        discrepancy_reason="",
        idempotency_key="",
    ):
        line = GoodsReceivingService.receive_line(
            goods_receipt=goods_receipt,
            po_line=po_line,
            delivered_quantity=received_quantity,
            quarantined_quantity=received_quantity,
            discrepancy_reason=discrepancy_reason,
            idempotency_key=idempotency_key,
        )
        return GoodsReceivingService.capture_batch(
            grn_line=line,
            manufacturer_batch_number=manufacturer_batch_number,
            manufacture_date=manufacture_date,
            expiry_date=expiry_date,
            received_quantity=received_quantity,
        )

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
        lines = list(
            PurchaseOrderLine.all_objects.filter(
                tenant_id=purchase_order.tenant_id, purchase_order=purchase_order
            )
        )
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
    def release_batch(
        *,
        batch: ReceivedBatch,
        released_by=None,
        actor=None,
        reason="",
        quantity=None,
        as_of=None,
        receiving_location=None,
    ) -> ReceivedBatch:
        """Move quarantined stock into accepted, released stock under strict quality gates.

        Refuses unless ALL conditions are met:
        - GoodsReceipt exists
        - ReceivingInspection exists
        - QualityDecision exists and is_releasable() == True
        - Batch not expired
        - Batch not recalled
        - Supplier qualification valid
        - Storage location compatible (controlled/cold-chain capabilities)
        """
        from apps.audit.service import log_audit
        from apps.medicines.provisioning import _is_cold_chain, _is_controlled
        from apps.procurement.models import QualityDecision, ReceivingInspection
        from apps.procurement.services.batch_quality_service import BatchQualityDecisionService
        from apps.procurement.services.supplier_governance_service import SupplierGovernanceService

        releaser = released_by or actor
        if releaser is None:
            raise ValidationError("Quality release requires a named releaser.")

        if not _may_release_quality(releaser):
            log_audit(
                tenant_id=batch.tenant_id,
                action="BATCH_QUALITY_RELEASE_REFUSED",
                model_name="ReceivedBatch",
                object_id=batch.pk,
                actor_id=getattr(releaser, "id", None),
                metadata={"reason": "NO_QUALITY_RELEASE_AUTHORITY"},
            )
            raise ValidationError("Actor lacks quality-release authority.")

        receipt = getattr(batch.grn_line, "goods_receipt", None)
        if receipt is None:
            raise ValidationError("Goods receipt does not exist for this batch.")

        inspection = ReceivingInspection.all_objects.filter(
            tenant=batch.tenant, goods_receipt=receipt
        ).first()
        if inspection is None:
            raise ValidationError("Receiving inspection does not exist for this goods receipt.")

        decision = QualityDecision.all_objects.filter(
            tenant=batch.tenant, batch=batch
        ).first()
        if decision is None:
            raise ValidationError(f"No quality decision recorded for batch {batch.manufacturer_batch_number}.")

        if not BatchQualityDecisionService.is_releasable(batch=batch):
            raise ValidationError(
                f"Batch {batch.manufacturer_batch_number} has decision {decision.decision} "
                "which is not releasable."
            )

        as_of_date = as_of or timezone.localdate()
        if batch.expiry_date <= as_of_date:
            raise ValidationError(f"Batch {batch.manufacturer_batch_number} is expired ({batch.expiry_date}).")

        if getattr(batch, "recall_status", "NONE") != "NONE":
            raise ValidationError(f"Batch {batch.manufacturer_batch_number} is subject to a regulatory recall.")

        arrival_dt = getattr(receipt, "arrival_time", None)
        receipt_date = arrival_dt.date() if arrival_dt and hasattr(arrival_dt, "date") else as_of_date

        reasons = SupplierGovernanceService.ineligibility_reasons(
            supplier=receipt.supplier, on_date=receipt_date
        )
        if reasons:
            raise ValidationError(f"Supplier {receipt.supplier.name} is ineligible: {reasons[0]}")

        if receiving_location is not None:
            if _is_controlled(batch.sku) and not receiving_location.controlled_drug_capability:
                raise ValidationError(f"Controlled SKU {batch.sku.sku_code} requires a controlled vault location.")
            if _is_cold_chain(batch.sku) and not receiving_location.cold_chain_capability:
                raise ValidationError(f"Cold-chain SKU {batch.sku.sku_code} requires a cold room location.")

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

        if batch.accepted_quantity >= (batch.received_quantity or 0):
            batch.quality_status = ReceivedBatch.QualityStatus.RELEASED
        elif batch.accepted_quantity > 0:
            batch.quality_status = ReceivedBatch.QualityStatus.PARTIALLY_RELEASED
        else:
            batch.quality_status = ReceivedBatch.QualityStatus.QUARANTINED

        batch.save(update_fields=[
            "accepted_quantity", "quarantined_quantity", "quality_status", "updated_at",
        ])

        line = batch.grn_line
        line.quarantined_quantity = max(0, (line.quarantined_quantity or 0) - quantity)
        line.accepted_quantity = (line.accepted_quantity or 0) + quantity
        line.save(update_fields=["quarantined_quantity", "accepted_quantity", "updated_at"])

        log_audit(
            tenant_id=batch.tenant_id,
            action="BATCH_QUALITY_RELEASED",
            model_name="ReceivedBatch",
            object_id=batch.pk,
            actor_id=getattr(releaser, "id", None),
            metadata={
                "batch": batch.manufacturer_batch_number,
                "released_quantity": quantity,
                "accepted_quantity": batch.accepted_quantity,
                "quality_status": batch.quality_status,
            },
        )
        return batch
