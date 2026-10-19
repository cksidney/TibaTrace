from __future__ import annotations

import decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

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
        session = ReceivingSession.all_objects.select_for_update().get(pk=session.pk, tenant_id=session.tenant_id)
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

        if (sku.expiry_tracking_required and not expiry_date) or (expiry_date and expiry_date <= timezone.localdate()):
            raise ValidationError("Expiry-tracked goods need a current expiry date; this batch is missing expiry or has already expired.")
        from apps.inventory.units import normalize_barcode_quantity
        scanned_quantity, evidence = normalize_barcode_quantity(tenant=session.tenant, sku=sku, barcode=scanned_barcode, quantity=scanned_quantity, whole=True)
        scan = ReceivingScan.all_objects.create(
            tenant=session.tenant,
            session=session,
            sku=sku,
            scanned_barcode=scanned_barcode,
            batch_number=batch_number,
            expiry_date=expiry_date,
            scanned_quantity=int(scanned_quantity),
            unit_evidence=evidence,
        )
        return scan

    @staticmethod
    @transaction.atomic
    def post_goods_receipt_note(*, session, destination_location, actor) -> GoodsReceipt:
        session = ReceivingSession.all_objects.select_for_update().get(pk=session.pk, tenant_id=session.tenant_id)
        if session.status != "ACTIVE":
            raise ValidationError("Receiving session has already been posted or closed.")
        scans = list(ReceivingScan.all_objects.filter(tenant_id=session.tenant_id, session=session).select_related("sku__package_definition"))
        if not scans:
            raise ValidationError("Cannot post a GRN for a session with no scanned items.")
        goods_receipt = GoodsReceivingService.start_goods_receipt(
            tenant=session.tenant, grn_number=f"GRN-{session.session_number}", purchase_order=session.purchase_order,
            receiving_branch=session.branch, receiver=actor, delivery_note_number=session.delivery_note_number,
        )
        from apps.inventory.receiving import stage_quarantine
        for scan in scans:
            po_line = PurchaseOrderLine.all_objects.get(tenant_id=session.tenant_id, purchase_order=session.purchase_order, sku=scan.sku)
            batch = GoodsReceivingService.receive_batch(goods_receipt=goods_receipt, po_line=po_line, manufacturer_batch_number=scan.batch_number, expiry_date=scan.expiry_date, received_quantity=scan.scanned_quantity)
            stage_quarantine(tenant=session.tenant, batch=batch, location=destination_location, actor=actor, reason=f"Receiving scan {scan.pk}; units {scan.unit_evidence}")

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


def _may_release_quality(actor, tenant_id=None) -> bool:
    return bool(actor and actor.is_active and actor.tenant_id in (None, tenant_id) and actor.has_capability(QUALITY_RELEASE_CAPABILITY, tenant_id=tenant_id))


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
        if purchase_order.tenant_id != tenant.pk or receiving_branch.tenant_id != tenant.pk or receiver is None or receiver.tenant_id not in (None, tenant.pk):
            raise ValidationError("Goods receipt identities must belong to this tenant and a named receiver.")
        if purchase_order.status not in {
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.ACKNOWLEDGED,
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
        if goods_receipt.tenant_id != po_line.tenant_id or goods_receipt.purchase_order_id != po_line.purchase_order_id or (sku and sku.pk != po_line.sku_id):
            raise ValidationError("Receipt, purchase-order line and SKU must describe the same tenant delivery.")
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
        if accepted_quantity:
            raise ValidationError("Receiving cannot accept stock before independent batch quality release.")
        quarantined_quantity = delivered_quantity - rejected_quantity
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

        if idempotency_key:
            # A retry over poor connectivity must not receive the same goods
            # twice. The key is unique per tenant, so the second call returns
            # the first call's line rather than adding to it.
            existing = GoodsReceiptLine.all_objects.filter(
                tenant=goods_receipt.tenant, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                if existing.goods_receipt_id != goods_receipt.pk or existing.po_line_id != po_line.pk or existing.delivered_quantity != delivered_quantity:
                    raise ValidationError("Receiving retry key belongs to a different receipt line.")
                return existing

        already_received = locked_po_line.received_quantity or 0
        if already_received + delivered_quantity > locked_po_line.ordered_quantity:
            raise ValidationError(
                f"Total received quantity cannot exceed ordered quantity: "
                f"{already_received} already received plus {delivered_quantity} "
                f"exceeds the {locked_po_line.ordered_quantity} ordered."
            )

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
        sku = sku or (grn_line.sku if grn_line else po_line.sku if po_line else None)
        if sku is None or (sku.expiry_tracking_required and expiry_date is None):
            raise ValidationError("Expiry-tracked goods require a batch expiry date.")
        if manufacture_date and expiry_date and manufacture_date >= expiry_date:
            raise ValidationError("Manufacture date must precede expiry date.")
        if expiry_date and expiry_date <= timezone.localdate():
            raise ValidationError("Cannot receive expired batch.")
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
        PurchaseOrderLine.all_objects.select_for_update().get(pk=po_line.pk, tenant_id=goods_receipt.tenant_id)
        if idempotency_key:
            prior = ReceivedBatch.all_objects.filter(tenant_id=goods_receipt.tenant_id, receipt_key=idempotency_key).first()
            if prior:
                if (prior.grn_line.goods_receipt_id, prior.grn_line.po_line_id, prior.manufacturer_batch_number, prior.expiry_date, prior.manufacture_date, prior.received_quantity) != (goods_receipt.pk, po_line.pk, manufacturer_batch_number, expiry_date, manufacture_date, received_quantity):
                    raise ValidationError("Receiving retry key belongs to a different delivery.")
                return prior
        line = GoodsReceivingService.receive_line(
            goods_receipt=goods_receipt,
            po_line=po_line,
            delivered_quantity=received_quantity,
            quarantined_quantity=received_quantity,
            discrepancy_reason=discrepancy_reason,
        )
        batch = GoodsReceivingService.capture_batch(
            grn_line=line,
            manufacturer_batch_number=manufacturer_batch_number,
            manufacture_date=manufacture_date,
            expiry_date=expiry_date,
            received_quantity=received_quantity,
        )

        if idempotency_key:
            batch.receipt_key = idempotency_key
            batch.save(update_fields=["receipt_key", "updated_at"])
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

        held = GoodsReceiptLine.all_objects.filter(tenant_id=goods_receipt.tenant_id, goods_receipt=goods_receipt, quarantined_quantity__gt=0).exists()
        goods_receipt.status = GoodsReceipt.Status.UNDER_INSPECTION if held else GoodsReceipt.Status.ACCEPTED
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
        idempotency_key="",
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

        type(batch.tenant).objects.select_for_update().get(pk=batch.tenant_id)
        batch = ReceivedBatch.all_objects.select_for_update(of=("self",)).select_related("grn_line__goods_receipt__supplier", "sku__manufactured_product", "sku__package_definition").get(pk=batch.pk, tenant_id=batch.tenant_id)
        releaser = released_by or actor
        command = {"quantity": str(quantity) if quantity is not None else None, "reason": str(reason).strip(), "location": str(receiving_location.pk) if receiving_location else None, "actor": str(releaser.pk) if releaser else None}
        from apps.procurement.models import BatchQualityRelease
        if idempotency_key:
            type(batch.tenant).objects.select_for_update().get(pk=batch.tenant_id)
            prior = BatchQualityRelease.all_objects.filter(tenant_id=batch.tenant_id, idempotency_key=idempotency_key).first()
            if prior:
                if prior.batch_id != batch.pk or prior.command != command:
                    raise ValidationError("Quality release retry key belongs to a different command.")
                return batch
        if not str(reason or "").strip():
            raise ValidationError("Quality release requires a recorded reason.")
        if batch.quality_status not in {"PENDING_INSPECTION", "QUARANTINED", "PARTIALLY_RELEASED"}:
            raise ValidationError("Only stock awaiting quality release can be released.")
        if releaser is None:
            raise ValidationError("Quality release requires a named releaser.")

        if not _may_release_quality(releaser, batch.tenant_id):
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
        ).order_by("-inspected_at", "-pk").first()

        decision = QualityDecision.all_objects.filter(
            tenant=batch.tenant, batch=batch
        ).order_by("-revision").first()

        if decision is None or not BatchQualityDecisionService.is_releasable(batch=batch):
            raise ValidationError("A recorded independent batch quality decision approving release is required.")
        if not decision.inspector_id or not decision.decision_by_id or receipt.received_by_id in {decision.inspector_id, decision.decision_by_id, releaser.pk}:
            raise ValidationError("Quality inspection, decision and release must be independent of the receiver.")
        if inspection and inspection.decision in {"REJECT", "DESTROY", "HOLD_FOR_INVESTIGATION"}:
            raise ValidationError("Resolve the receipt inspection hold before releasing this batch.")

        as_of_date = as_of or timezone.localdate()
        if (batch.sku.expiry_tracking_required and not batch.expiry_date) or (batch.expiry_date and batch.expiry_date <= as_of_date):
            raise ValidationError(f"Batch {batch.manufacturer_batch_number} is expired ({batch.expiry_date}).")

        if getattr(batch, "recall_status", "NONE") != "NONE":
            raise ValidationError(f"Batch {batch.manufacturer_batch_number} is subject to a regulatory recall.")

        reasons = SupplierGovernanceService.ineligibility_reasons(
            supplier=receipt.supplier, on_date=as_of_date,
            controlled=_is_controlled(batch.sku), cold_chain=_is_cold_chain(batch.sku),
            medicine=batch.sku.product_kind == "MEDICINE",
        )
        if reasons:
            raise ValidationError(f"Supplier {receipt.supplier} is ineligible: {reasons[0]}")

        if receiving_location is not None:
            if _is_controlled(batch.sku) and not receiving_location.controlled_drug_capability:
                raise ValidationError(f"Controlled SKU {batch.sku.sku_code} requires a controlled vault location.")
            if _is_cold_chain(batch.sku) and not receiving_location.cold_chain_capability:
                raise ValidationError(f"Cold-chain SKU {batch.sku.sku_code} requires a cold room location.")

        already_released = batch.accepted_quantity or 0
        from apps.procurement.models import SupplierReturnLine
        return_lines = SupplierReturnLine.all_objects.filter(tenant_id=batch.tenant_id, batch=batch, supplier_return__return_category="QUALITY_REJECTION").exclude(supplier_return__status="REJECTED")
        returned = return_lines.aggregate(total=models.Sum("quantity"))["total"] or 0
        dispatched_returns = return_lines.filter(supplier_return__status__in=["DISPATCHED", "CREDIT_PENDING", "CLOSED"]).aggregate(total=models.Sum("quantity"))["total"] or 0
        outstanding = max(0, (batch.received_quantity or 0) - already_released - (batch.rejected_quantity or 0) - returned)
        quantity = decimal.Decimal(str(outstanding if quantity is None else quantity))
        if not quantity.is_finite() or quantity != quantity.to_integral_value():
            raise ValidationError("Release a whole number of the confirmed base units.")
        quantity = int(quantity)

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

        if batch.accepted_quantity + (batch.rejected_quantity or 0) + dispatched_returns >= batch.received_quantity:
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

        if idempotency_key:
            BatchQualityRelease.all_objects.create(tenant_id=batch.tenant_id, batch=batch, released_by=releaser, quantity=quantity, command=command, idempotency_key=idempotency_key)
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
