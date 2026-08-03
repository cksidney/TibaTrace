"""Stage 2B.1 — procurement and receiving.

Generates the paper trail that stock arrives through: requisition, approval,
purchase order, approval, send, goods receipt, batch capture, close.

**It stops at quarantined batches.** Nothing here releases quality, posts a
receipt, writes a ledger entry or touches a balance. That boundary is the point
of the increment: received stock is not available stock, and the step that makes
it available is a separate decision by a different person. A generator that ran
past this line would create available-to-promise inventory that no quality
release ever authorised.

Split into nine independently resumable stages (M1–M5, N1–N4) rather than two
large ones. Approvals, sends and batch capture are not idempotent lifecycle
transitions -- resuming into the middle of a coarse stage would repeat them, so
each transition gets its own checkpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.medicines.provisioning import _is_cold_chain, _is_controlled
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRevision,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    ReceivingSession,
    Supplier,
    SupplierProductAgreement,
)
from apps.procurement.services.procurement_service import ProcurementService
from apps.procurement.services.receiving_service import (
    GoodsReceivingService,
    ReceivingService,
)
from apps.procurement.services.supplier_qualification_service import (
    COLD_CHAIN_QUALIFICATION,
    CONTROLLED_DRUG_QUALIFICATION,
    SupplierQualificationService,
)

from . import synthetic as syn
from .stages import REF, Stage

STORY_PROCUREMENT = "NC-OPS-PROCUREMENT-001"
STORY_RECEIVING = "NC-OPS-RECEIVING-001"

#: How many requisitions the increment raises. Each becomes one or two orders.
REQUISITION_COUNT = 12
#: Lines per requisition. Bounded so a run stays reviewable.
LINES_PER_REQUISITION = 11
#: Requisitions whose approval is partial -- some lines ordered, some left
#: outstanding, which is what a real replenishment cycle looks like.
PARTIAL_ORDER_EVERY = 3
#: Orders that get a revision before receipt.
REVISE_EVERY = 4
#: How far back the earliest requisition is raised. Must stay inside the
#: supplier qualification window established by Stage 2A (200 days).
PROCUREMENT_WINDOW_DAYS = 170

#: Delivery shapes, cycled deterministically across receipts.
#: (label, fraction of ordered quantity delivered, disposition)
DELIVERY_SHAPES = (
    ("complete", 1.00, "clean"),
    ("partial", 0.60, "clean"),
    ("short", 0.85, "clean"),
    ("damaged", 1.00, "damaged"),
    ("excursion", 1.00, "excursion"),
    ("near_expiry", 1.00, "near_expiry"),
    ("complete", 1.00, "clean"),
    ("rejected_line", 1.00, "rejected"),
)


def _agreement_for(ctx, sku):
    """The preferred active agreement for a SKU, deterministically."""
    return (
        SupplierProductAgreement.all_objects.filter(
            tenant=ctx.tenant, sku=sku, status=SupplierProductAgreement.Status.ACTIVE
        )
        .select_related("supplier")
        .order_by("-is_preferred", "supplier__supplier_code")
        .first()
    )


def _supplier_catalogue(ctx, supplier):
    """Every SKU this supplier has an active agreement for, ordered."""
    return [
        (agreement.sku, agreement)
        for agreement in SupplierProductAgreement.all_objects.filter(
            tenant=ctx.tenant, supplier=supplier,
            status=SupplierProductAgreement.Status.ACTIVE,
        ).select_related("sku__manufactured_product__clinical_product__dose_form")
        .order_by("sku__sku_code")
    ]


def _supplier_may_supply(supplier, sku) -> bool:
    """Whether the supplier holds the licences this SKU requires."""
    if _is_controlled(sku) and not SupplierQualificationService.holds(
        supplier=supplier, qualification_type=CONTROLLED_DRUG_QUALIFICATION
    ):
        return False
    if _is_cold_chain(sku) and not SupplierQualificationService.holds(
        supplier=supplier, qualification_type=COLD_CHAIN_QUALIFICATION
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# M1 — requisitions
# ---------------------------------------------------------------------------


class StageM1Requisitions(Stage):
    id = "M1"
    label = "Purchase requisitions"

    def plan(self, ctx):
        return {"purchase_requisitions": REQUISITION_COUNT}

    def rehydrate(self, ctx):
        for index in range(REQUISITION_COUNT):
            reference = f"{REF}-REQ-{index:03d}"
            requisition = ctx.owned_reference(PurchaseRequisition, reference)
            if requisition is not None:
                ctx.put(f"requisition:{index}", requisition)

    @transaction.atomic
    def run(self, ctx):
        from apps.medicines.models import CommercialSKU

        skus = list(
            CommercialSKU.all_objects.filter(tenant=ctx.tenant).order_by("sku_code")
        )
        suppliers = list(
            Supplier.all_objects.filter(
                tenant=ctx.tenant, status__in=(Supplier.Status.APPROVED, Supplier.Status.ACTIVE)
            ).order_by("supplier_code")
        )
        if not suppliers:
            ctx.defer(
                domain="procurement", stage=self.id,
                reason="No approved suppliers; Stage 2A must run first.",
                required_service="Stage 2A supplier provisioning",
            )
            return
        if not skus:
            ctx.defer(
                domain="procurement", stage=self.id,
                reason="The tenant has no commercial SKUs; Stage 2A must run first.",
                required_service="Stage 2A catalogue provisioning",
            )
            return

        requester = ctx.get("user:procurement")
        warehouse = ctx.get("site:warehouse")

        for index in range(REQUISITION_COUNT):
            reference = f"{REF}-REQ-{index:03d}"
            existing = ctx.owned_reference(PurchaseRequisition, reference)
            if existing is not None:
                ctx.put(f"requisition:{index}", existing)
                ctx.note_reuse("purchase_requisitions", reference)
                ctx.add_count("purchase_requisitions", 1)
                continue

            # Spread backwards over the operating period, but bounded by
            # supplier qualification validity: Stage 2A dates qualifications
            # from as-of minus 200 days, and an order placed before its
            # supplier was qualified is correctly refused by governance.
            raised = ctx.as_of - timedelta(days=PROCUREMENT_WINDOW_DAYS - index * 17)
            requisition = ProcurementService.create_requisition(
                tenant=ctx.tenant,
                requesting_branch=warehouse,
                requester=requester,
                requisition_number=reference,
                requested_delivery_date=raised + timedelta(days=14),
                justification="Replenishment cycle for the demonstration scenario.",
            )

            # One supplier per requisition. create_priced_po_from_requisition
            # requires an APPROVED requisition, and raising the first order
            # moves it to PARTIALLY_ORDERED -- so a requisition spanning several
            # suppliers can only ever yield one order, and the rest are refused.
            # Buying a basket from one counterparty is also what a replenishment
            # cycle actually looks like.
            supplier = suppliers[index % len(suppliers)]
            supplied = [
                (sku, agreement)
                for sku, agreement in _supplier_catalogue(ctx, supplier)
                if _supplier_may_supply(supplier, sku)
            ]
            # Weighted demand: a stable subset moves more often than the tail,
            # so consumption is not uniform across the catalogue.
            chosen = sorted(
                supplied,
                key=lambda pair: syn.stable_int(ctx.seed, "demand", index, pair[0].sku_code),
            )[:LINES_PER_REQUISITION]
            for sku, agreement in chosen:
                quantity = 20 + syn.stable_int(ctx.seed, "qty", reference, sku.sku_code) % 180
                ProcurementService.add_line(
                    requisition=requisition, sku=sku, requested_quantity=quantity,
                    estimated_unit_cost=agreement.agreed_unit_price,
                )
                ctx.add_count("requisition_lines", 1)
            ctx.put(f"requisition_supplier:{index}", supplier)

            ctx.own(requisition, domain="purchase_requisitions", stage=self.id,
                    story_id=STORY_PROCUREMENT, reference=reference,
                    branch_reference=warehouse.code,
                    purpose="Replenishment demand for the central warehouse.",
                    relationship_group=f"{REF}-PROCURE-{index:03d}")
            ctx.put(f"requisition:{index}", requisition)
            ctx.add_count("purchase_requisitions", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# M2 — requisition approvals
# ---------------------------------------------------------------------------


class StageM2RequisitionApproval(Stage):
    id = "M2"
    label = "Requisition submission and approval"
    requires = ("M1",)

    def rehydrate(self, ctx):
        StageM1Requisitions().rehydrate(ctx)

    def run(self, ctx):
        # The requester may not approve their own requisition -- the service
        # refuses it, so the scenario uses the operations manager.
        approver = ctx.get("user:ops")
        for index in range(REQUISITION_COUNT):
            if not ctx.has(f"requisition:{index}"):
                continue
            requisition = ctx.get(f"requisition:{index}")
            requisition.refresh_from_db()
            if requisition.status == PurchaseRequisition.Status.DRAFT:
                ProcurementService.submit_requisition(requisition=requisition)
                requisition.refresh_from_db()
            if requisition.status in {
                PurchaseRequisition.Status.SUBMITTED,
                PurchaseRequisition.Status.UNDER_REVIEW,
            }:
                ProcurementService.approve_requisition(
                    requisition=requisition, approver=approver
                )
                ctx.add_count("requisitions_approved", 1)
            ctx.stage_results[self.id].last_key = requisition.requisition_number


# ---------------------------------------------------------------------------
# M3 — purchase orders
# ---------------------------------------------------------------------------


class StageM3PurchaseOrders(Stage):
    id = "M3"
    label = "Purchase orders"
    requires = ("M2",)

    def plan(self, ctx):
        return {"purchase_orders": REQUISITION_COUNT + REQUISITION_COUNT // PARTIAL_ORDER_EVERY}

    def rehydrate(self, ctx):
        StageM1Requisitions().rehydrate(ctx)
        for index in range(REQUISITION_COUNT * 2):
            reference = f"{REF}-PO-{index:03d}"
            order = ctx.owned_reference(PurchaseOrder, reference)
            if order is not None:
                ctx.put(f"po:{index}", order)
                ctx.put(f"requisition_supplier:{index}", order.supplier)

    def run(self, ctx):
        creator = ctx.get("user:procurement")
        warehouse = ctx.get("site:warehouse")
        po_index = 0

        for index in range(REQUISITION_COUNT):
            if not ctx.has(f"requisition:{index}") or not ctx.has(
                f"requisition_supplier:{index}"
            ):
                continue
            requisition = ctx.get(f"requisition:{index}")
            requisition.refresh_from_db()
            supplier = ctx.get(f"requisition_supplier:{index}")

            reference = f"{REF}-PO-{po_index:03d}"
            existing = ctx.owned_reference(PurchaseOrder, reference)
            if existing is not None:
                ctx.put(f"po:{po_index}", existing)
                ctx.note_reuse("purchase_orders", reference)
                ctx.add_count("purchase_orders", 1)
                po_index += 1
                continue

            if requisition.status != PurchaseRequisition.Status.APPROVED:
                continue

            lines = list(
                PurchaseRequisitionLine.all_objects.filter(
                    tenant=ctx.tenant, requisition=requisition
                ).select_related("sku").order_by("sku__sku_code")
            )
            # Order only part of the approved demand on some cycles; the rest
            # stays outstanding, which is what replenishment actually leaves
            # behind.
            partial = index % PARTIAL_ORDER_EVERY == 0
            if partial:
                lines = lines[: max(1, len(lines) // 2)]

            lines_data = [
                {
                    "requisition_line": str(line.pk),
                    "quantity": line.outstanding_quantity,
                    "unit_cost": (
                        _agreement_for(ctx, line.sku).agreed_unit_price
                        if _agreement_for(ctx, line.sku) else None
                    ),
                    "requires_cold_chain": _is_cold_chain(line.sku),
                }
                for line in lines
                if line.outstanding_quantity > 0 and _agreement_for(ctx, line.sku)
            ]
            if not lines_data:
                continue

            order_date = requisition.requested_delivery_date - timedelta(days=10)
            lead_time = 3 + syn.stable_int(ctx.seed, "lead", reference) % 12
            try:
                order = ProcurementService.create_priced_po_from_requisition(
                    tenant=ctx.tenant, supplier=supplier, requisition=requisition,
                    ordering_branch=warehouse, creator=creator,
                    lines_data=lines_data, po_number=reference,
                    order_date=order_date,
                    expected_delivery_date=order_date + timedelta(days=lead_time),
                )
            except ValidationError:
                # Governance refused -- suspended supplier, lapsed licence, or a
                # requisition already partly ordered. Recorded as evidence, not
                # routed around.
                ctx.add_count("procurement_blocked_on_supplier", 1)
                continue

            ctx.own(order, domain="purchase_orders", stage=self.id,
                    story_id=STORY_PROCUREMENT, reference=reference,
                    branch_reference=warehouse.code,
                    purpose=f"Order to {supplier.supplier_code}"
                            f"{' (partial)' if partial else ''}.",
                    relationship_group=f"{REF}-PROCURE-{index:03d}")
            ctx.put(f"po:{po_index}", order)
            ctx.add_count("purchase_orders", 1)
            ctx.add_count(f"purchase_orders.supplier.{supplier.supplier_code}", 1)
            if partial:
                ctx.add_count("purchase_orders_partial", 1)
            ctx.stage_results[self.id].last_key = reference
            po_index += 1

        ctx.put("po_count", po_index)


# ---------------------------------------------------------------------------
# M4 — approvals
# ---------------------------------------------------------------------------


def _orders(ctx):
    """Every purchase order this run owns, in deterministic order."""
    return [
        ctx.get(key)
        for key in sorted(k for k in ctx.registry if k.startswith("po:"))
    ]


class StageM4PurchaseOrderApproval(Stage):
    id = "M4"
    label = "Purchase-order approval and release"
    requires = ("M3",)

    def rehydrate(self, ctx):
        StageM3PurchaseOrders().rehydrate(ctx)

    def run(self, ctx):
        # The raiser may not approve their own order; the service refuses it.
        approver = ctx.get("user:ops")
        for order in _orders(ctx):
            order.refresh_from_db()
            if order.status == PurchaseOrder.Status.DRAFT:
                ProcurementService.approve_purchase_order(
                    purchase_order=order, approver=approver
                )
                order.refresh_from_db()
                ctx.add_count("purchase_orders_approved", 1)
            ctx.stage_results[self.id].last_key = order.po_number


# ---------------------------------------------------------------------------
# M5 — revisions and sending
# ---------------------------------------------------------------------------


class StageM5PurchaseOrderRelease(Stage):
    id = "M5"
    label = "Purchase-order revisions and sending"
    requires = ("M4",)

    def rehydrate(self, ctx):
        StageM3PurchaseOrders().rehydrate(ctx)

    def run(self, ctx):
        actor = ctx.get("user:procurement")
        approver = ctx.get("user:ops")
        for index, order in enumerate(_orders(ctx)):
            order.refresh_from_db()

            # Revise before sending, so the supplier's copy is correct.
            if index % REVISE_EVERY == 0 and order.status == PurchaseOrder.Status.APPROVED:
                already_revised = PurchaseOrderRevision.all_objects.filter(
                    tenant=ctx.tenant, purchase_order=order
                ).exists()
                if not already_revised:
                    ProcurementService.revise_purchase_order(
                        purchase_order=order, actor=actor,
                        reason="Delivery date renegotiated with the supplier.",
                        expected_delivery_date=order.expected_delivery_date
                        + timedelta(days=5),
                    )
                    order.refresh_from_db()
                    ctx.add_count("purchase_order_revisions", 1)

            # A revision returns the order to SUBMITTED: the approval covered
            # the prior version, so it does not carry over to the revised one.
            # Re-approving is the point of the reset, not a workaround for it.
            if order.status == PurchaseOrder.Status.SUBMITTED:
                order.status = PurchaseOrder.Status.DRAFT
                order.save(update_fields=["status", "updated_at"])
                ProcurementService.approve_purchase_order(
                    purchase_order=order, approver=approver
                )
                order.refresh_from_db()
                ctx.add_count("purchase_orders_reapproved_after_revision", 1)

            if order.status == PurchaseOrder.Status.APPROVED:
                ProcurementService.send_po(purchase_order=order)
                order.refresh_from_db()
                ctx.add_count("purchase_orders_sent", 1)
            ctx.stage_results[self.id].last_key = order.po_number


# ---------------------------------------------------------------------------
# N1 — goods receipt headers
# ---------------------------------------------------------------------------


def _receivable(ctx):
    """Orders a receipt may be opened against."""
    return [
        order for order in _orders(ctx)
        if order.status in {PurchaseOrder.Status.SENT,
                            PurchaseOrder.Status.PARTIALLY_RECEIVED}
    ]


class StageN1GoodsReceipts(Stage):
    id = "N1"
    label = "Goods receipt headers"
    requires = ("M5",)

    def rehydrate(self, ctx):
        StageM3PurchaseOrders().rehydrate(ctx)
        for index in range(REQUISITION_COUNT * 2):
            receipt = ctx.owned_reference(GoodsReceipt, f"{REF}-GRN-{index:03d}")
            if receipt is not None:
                ctx.put(f"grn:{index}", receipt)

    def run(self, ctx):
        receiver = ctx.get("user:receiving")
        warehouse = ctx.get("site:warehouse")

        for index, order in enumerate(_receivable(ctx)):
            reference = f"{REF}-GRN-{index:03d}"
            existing = ctx.owned_reference(GoodsReceipt, reference)
            if existing is not None:
                ctx.put(f"grn:{index}", existing)
                ctx.note_reuse("goods_receipts", reference)
                ctx.add_count("goods_receipts", 1)
                continue

            # The delivery note is unique per supplier -- the same note received
            # twice is the classic double-receipt.
            delivery_note = f"DN-{order.supplier.supplier_code}-{index:04d}"
            # Suppliers deliver late by varying amounts; a fixed offset would
            # make every delivery land exactly on its promised date.
            slip = syn.stable_int(ctx.seed, "arrive", reference) % 5
            arrival = datetime.combine(
                order.expected_delivery_date + timedelta(days=slip),
                time(hour=8 + syn.stable_int(ctx.seed, "hour", reference) % 8),
                tzinfo=UTC,
            )
            receipt = GoodsReceivingService.start_goods_receipt(
                tenant=ctx.tenant, grn_number=reference, purchase_order=order,
                receiving_branch=warehouse, receiver=receiver,
                delivery_note_number=delivery_note,
                arrival_time=arrival,
            )
            ctx.own(receipt, domain="goods_receipts", stage=self.id,
                    story_id=STORY_RECEIVING, reference=reference,
                    branch_reference=warehouse.code,
                    purpose=f"Delivery from {order.supplier.supplier_code} "
                            f"against {order.po_number}.",
                    relationship_group=f"{REF}-RECEIVE-{index:03d}")
            ctx.put(f"grn:{index}", receipt)
            ctx.put(f"grn_order:{index}", order)
            ctx.add_count("goods_receipts", 1)
            ctx.add_count(f"goods_receipts.supplier.{order.supplier.supplier_code}", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# N2 — scan-based receiving session
# ---------------------------------------------------------------------------


class StageN2ReceivingSession(Stage):
    """Exercise the scan-to-receive path, and stop before it posts.

    `ReceivingService` is the authoritative scan path: open a session, scan each
    carton, then post. This stage runs the first two and deliberately not the
    third -- `post_goods_receipt_note` writes a GRN into inventory, which is
    exactly the boundary this increment holds. Running it here would create
    available stock no quality release authorised.

    The session is therefore left ACTIVE with its scans recorded, which is also
    what a real receiving bay looks like mid-delivery.
    """

    id = "N2"
    label = "Scan-based receiving session (unposted)"
    requires = ("N1",)

    def rehydrate(self, ctx):
        StageN1GoodsReceipts().rehydrate(ctx)

    def run(self, ctx):
        receipts = _receipts(ctx)
        if not receipts:
            return
        receiver = ctx.get("user:receiving")
        warehouse = ctx.get("site:warehouse")

        # One session, on the first receipt's order. The scan path is a
        # capability to demonstrate, not a second way to receive everything.
        receipt_index, receipt = receipts[0]
        reference = f"{REF}-RCVSESSION-{receipt_index:03d}"
        if ctx.owned_reference(ReceivingSession, reference) is not None:
            ctx.note_reuse("receiving_sessions", reference)
            ctx.add_count("receiving_sessions", 1)
            return

        order = receipt.purchase_order
        session = ReceivingService.open_receiving_session(
            tenant=ctx.tenant,
            purchase_order=order,
            branch=warehouse,
            delivery_note_number=f"{receipt.delivery_note_number}-SCAN",
            received_by=receiver,
        )
        ctx.own(session, domain="receiving_sessions", stage=self.id,
                story_id=STORY_RECEIVING, reference=reference,
                branch_reference=warehouse.code,
                purpose="Scan-to-receive session, left unposted at the Stage 2B.1 boundary.",
                relationship_group=f"{REF}-RECEIVE-{receipt_index:03d}")
        ctx.add_count("receiving_sessions", 1)

        lines = list(
            PurchaseOrderLine.all_objects.filter(
                tenant=ctx.tenant, purchase_order=order
            ).select_related("sku").order_by("sku__sku_code")
        )
        for line_index, po_line in enumerate(lines):
            sku = po_line.sku
            scan_reference = f"{reference}-SCAN-{line_index:02d}"
            # record_scan refuses an expiry on or before today, so scanned stock
            # is always dated forward of the run's as-of date.
            expiry = ctx.as_of + timedelta(
                days=180 + syn.stable_int(ctx.seed, "scanexp", scan_reference) % 540
            )
            try:
                scan = ReceivingService.record_scan(
                    session=session,
                    sku=sku,
                    # No GTIN is invented: the scanned barcode is whatever the
                    # SKU already carries, and empty where it carries none.
                    scanned_barcode=sku.default_barcode or "",
                    batch_number=(
                        f"SCAN-{syn.stable_int(ctx.seed, 'scanbatch', scan_reference) % 1_000_000:06d}"
                    ),
                    expiry_date=expiry,
                    scanned_quantity=max(1, po_line.ordered_quantity // 4),
                )
            except ValidationError:
                ctx.add_count("receiving_scans_refused", 1)
                continue
            ctx.own(scan, domain="receiving_scans", stage=self.id,
                    story_id=STORY_RECEIVING, reference=scan_reference,
                    branch_reference=warehouse.code,
                    purpose=f"Scanned carton of {sku.sku_code}.",
                    relationship_group=f"{REF}-RECEIVE-{receipt_index:03d}")
            ctx.add_count("receiving_scans", 1)

        # Left ACTIVE on purpose: posting is Stage 2B.2.
        session.refresh_from_db()
        if session.status != "ACTIVE":
            raise ValidationError(
                f"Receiving session {session.session_number} is {session.status}. "
                "Stage 2B.1 leaves sessions unposted; posting writes stock."
            )
        ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# N3 — batch capture
# ---------------------------------------------------------------------------


def _receipts(ctx):
    return [
        (int(key.split(":")[1]), ctx.get(key))
        for key in sorted(k for k in ctx.registry if k.startswith("grn:"))
    ]


class StageN3BatchCapture(Stage):
    id = "N3"
    label = "Batch capture (quarantined)"
    requires = ("N1",)

    def plan(self, ctx):
        return {"received_batches": REQUISITION_COUNT * LINES_PER_REQUISITION}

    def rehydrate(self, ctx):
        StageN1GoodsReceipts().rehydrate(ctx)

    def run(self, ctx):
        for receipt_index, receipt in _receipts(ctx):
            receipt.refresh_from_db()
            if receipt.status in {GoodsReceipt.Status.CLOSED,
                                  GoodsReceipt.Status.ACCEPTED}:
                continue
            shape, fraction, disposition = DELIVERY_SHAPES[
                receipt_index % len(DELIVERY_SHAPES)
            ]
            self._capture(ctx, receipt_index, receipt, shape, fraction, disposition)
            ctx.stage_results[self.id].last_key = receipt.grn_number

    def _capture(self, ctx, receipt_index, receipt, shape, fraction, disposition):
        order = receipt.purchase_order
        lines = list(
            PurchaseOrderLine.all_objects.filter(
                tenant=ctx.tenant, purchase_order=order
            ).select_related("sku").order_by("sku__sku_code")
        )

        for line_index, po_line in enumerate(lines):
            sku = po_line.sku
            reference = f"{REF}-BATCH-{receipt_index:03d}-{line_index:02d}"
            if ctx.owned_reference(ReceivedBatch, reference) is not None:
                ctx.note_reuse("received_batches", reference)
                ctx.add_count("received_batches", 1)
                continue

            delivered = int(po_line.ordered_quantity * fraction)
            if delivered <= 0:
                continue

            # Expiry spread: most stock is long-dated, some is near expiry.
            # Deliberately never in the past -- receiving expired stock is a
            # different scenario and belongs to a later stage.
            if disposition == "near_expiry" and line_index == 0:
                months = 2
            else:
                months = 6 + syn.stable_int(ctx.seed, "expiry", reference) % 30
            expiry = receipt.arrival_time.date() + timedelta(days=months * 30)
            manufactured = receipt.arrival_time.date() - timedelta(
                days=30 + syn.stable_int(ctx.seed, "mfg", reference) % 300
            )

            batch_number = (
                f"{sku.sku_code[-6:]}-"
                f"{syn.stable_int(ctx.seed, 'batch', reference) % 1_000_000:06d}"
            )
            try:
                batch = GoodsReceivingService.receive_batch(
                    goods_receipt=receipt,
                    po_line=po_line,
                    manufacturer_batch_number=batch_number,
                    expiry_date=expiry,
                    received_quantity=delivered,
                    manufacture_date=manufactured,
                    discrepancy_reason=_DISCREPANCY_REASONS.get(disposition, ""),
                    # Idempotency key so a replayed receive does not book the
                    # same delivery twice.
                    idempotency_key=reference,
                )
            except ValidationError:
                ctx.add_count("batches_refused", 1)
                continue

            ctx.own(batch, domain="received_batches", stage=self.id,
                    story_id=STORY_RECEIVING, reference=reference,
                    branch_reference=receipt.receiving_branch.code,
                    purpose=f"{shape} delivery of {sku.sku_code}, quarantined.",
                    relationship_group=f"{REF}-RECEIVE-{receipt_index:03d}",
                    reset_eligible=False)
            ctx.add_count("received_batches", 1)
            ctx.add_count("goods_receipt_lines", 1)
            ctx.add_count(f"received_batches.shape.{shape}", 1)
            if _is_cold_chain(sku):
                ctx.add_count("received_batches.cold_chain", 1)
            if _is_controlled(sku):
                ctx.add_count("received_batches.controlled", 1)
            if months <= 3:
                ctx.add_count("received_batches.near_expiry", 1)


_DISCREPANCY_REASONS = {
    "damaged": "Outer carton damaged in transit; line held for inspection.",
    "excursion": "Cold-chain temperature excursion logged on arrival.",
    "rejected": "Packaging integrity failure; line refused at the bay.",
    "near_expiry": "Short-dated stock accepted into quarantine pending review.",
}


# ---------------------------------------------------------------------------
# N4 — receipt closure
# ---------------------------------------------------------------------------


class StageN4ReceiptClosure(Stage):
    id = "N4"
    label = "Goods receipt closure"
    requires = ("N3",)

    def rehydrate(self, ctx):
        StageN1GoodsReceipts().rehydrate(ctx)

    def run(self, ctx):
        for _index, receipt in _receipts(ctx):
            receipt.refresh_from_db()
            if receipt.status == GoodsReceipt.Status.CLOSED:
                continue
            try:
                GoodsReceivingService.close_goods_receipt(goods_receipt=receipt)
                ctx.add_count("goods_receipts_closed", 1)
            except ValidationError:
                ctx.add_count("goods_receipts_not_closable", 1)
            ctx.stage_results[self.id].last_key = receipt.grn_number

        # Assert the boundary rather than trust it. Everything received in this
        # increment must still be quarantined: nothing has been released, and
        # nothing has reached the ledger.
        # capture_batch leaves quality_status at PENDING_INSPECTION and sets
        # quarantined_quantity to the whole delivery -- that pairing is this
        # repository's "held on arrival", and the QUARANTINED enum value is for
        # an explicit later quality decision. Asserting on quality_status alone
        # would therefore pass a batch that had been released.
        released = ReceivedBatch.all_objects.filter(
            tenant=ctx.tenant, quality_status=ReceivedBatch.QualityStatus.RELEASED
        ).count()
        if released:
            raise ValidationError(
                f"{released} batch(es) are RELEASED. Stage 2B.1 stops at quarantine; "
                "quality release and inventory posting are Stage 2B.2."
            )
        unheld = ReceivedBatch.all_objects.filter(tenant=ctx.tenant).exclude(
            quarantined_quantity=models.F("received_quantity")
        ).count()
        if unheld:
            raise ValidationError(
                f"{unheld} received batch(es) are not fully held. Every unit received "
                "in this increment must remain quarantined."
            )


STAGE_2B_1: tuple[Stage, ...] = (
    StageM1Requisitions(),
    StageM2RequisitionApproval(),
    StageM3PurchaseOrders(),
    StageM4PurchaseOrderApproval(),
    StageM5PurchaseOrderRelease(),
    StageN1GoodsReceipts(),
    StageN2ReceivingSession(),
    StageN3BatchCapture(),
    StageN4ReceiptClosure(),
)
