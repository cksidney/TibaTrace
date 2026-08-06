"""Stage 2C — Stock Mobility & Reservation Engine generator stages.

Implements:
- Inter-Branch Stock Transfers (Warehouse -> Branch & Branch -> Branch)
- Stock transfer approvals, allocation, dispatch, receiving, rejection, cancellation
- Inventory Reservations & Allocation Locking
- Reservation expiry & release
- Balance rebuild & inventory mobility boundary checks

Truth label / Policy:
- Authoritative domain services only: StockTransferService, InventoryReservationService, FEFOAllocationService, InventoryLedgerService, InventoryBalanceService.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StockTransfer,
    StockTransferLine,
)
from apps.inventory.services import (
    InventoryBalanceService,
    InventoryReservationService,
    StockTransferService,
)

from . import synthetic as syn
from .stages import REF, Stage

STORY_MOBILITY = "NC-OPS-MOBILITY-001"


def _scenario_balances(ctx):
    """Retrieve available inventory balances for the scenario tenant."""
    return InventoryBalance.all_objects.filter(
        tenant=ctx.tenant, available__gt=0
    ).select_related("branch", "location", "sku", "inventory_batch")


# ---------------------------------------------------------------------------
# T1 — transfer planning
# ---------------------------------------------------------------------------


class StageT1TransferPlanning(Stage):
    id = "T1"
    label = "Stock transfer planning"
    requires = ("S2",)

    def rehydrate(self, ctx):
        pass

    def run(self, ctx):
        rnd = syn.rng(ctx.seed, "stage2c-transfer-planning")
        balances = list(_scenario_balances(ctx))

        if not balances:
            raise ValidationError("No available inventory balances found for transfer planning.")

        # Group available balances by branch
        branch_balances = {}
        for bal in balances:
            branch_balances.setdefault(bal.branch_id, []).append(bal)

        branches = list(branch_balances.keys())

        # Target numbers: 50 Warehouse -> Branch transfers, 25 Branch -> Branch transfers
        # Outcome distribution: ~90% COMPLETED, ~5% REJECTED, ~5% CANCELLED
        planned_transfers = []
        transfer_seq = 1

        for src_branch_id, bal_list in branch_balances.items():
            other_branches = [b for b in branches if b != src_branch_id]
            if not other_branches:
                continue

            for bal in bal_list[:15]:
                dest_branch_id = rnd.choice(other_branches)
                dest_loc = InventoryLocation.all_objects.filter(
                    tenant=ctx.tenant, branch_id=dest_branch_id, status=InventoryLocation.Status.ACTIVE
                ).first()

                if not dest_loc or bal.location == dest_loc:
                    continue

                outcome_roll = rnd.random()
                if outcome_roll < 0.90:
                    outcome = "COMPLETED"
                elif outcome_roll < 0.95:
                    outcome = "REJECTED"
                else:
                    outcome = "CANCELLED"

                transfer_num = f"TRF-{ctx.as_of.strftime('%Y%m%d')}-{transfer_seq:04d}"
                transfer_seq += 1

                qty = max(Decimal("1"), Decimal(str(int(bal.available * Decimal("0.3")) or 1)))

                planned_transfers.append({
                    "transfer_number": transfer_num,
                    "source_branch_id": src_branch_id,
                    "dest_branch_id": dest_branch_id,
                    "source_location": bal.location,
                    "dest_location": dest_loc,
                    "sku": bal.sku,
                    "quantity": qty,
                    "outcome": outcome,
                })

        ctx.put("mobility:transfer_plan", planned_transfers)
        ctx.add_count("transfers_planned", len(planned_transfers))


# ---------------------------------------------------------------------------
# T2 — stock transfers execution
# ---------------------------------------------------------------------------


class StageT2StockTransfers(Stage):
    id = "T2"
    label = "Stock transfer execution"
    requires = ("T1",)

    def rehydrate(self, ctx):
        StageT1TransferPlanning().run(ctx)

    def run(self, ctx):
        requester = ctx.get("user:ops")
        approver = ctx.get("user:quality")
        receiver = ctx.get("user:receiving")
        planned = ctx.get("mobility:transfer_plan")

        from apps.organizations.models import Location as BranchLocation

        for item in planned:
            ref_str = item["transfer_number"]
            reference = f"{REF}-TRF-{ref_str}"

            if ctx.owned_reference(StockTransfer, reference) is not None or StockTransfer.all_objects.filter(
                tenant=ctx.tenant, transfer_number=ref_str
            ).exists():
                ctx.note_reuse("transfers", reference)
                ctx.add_count("stock_transfers", 1)
                continue

            # all_objects with an explicit tenant filter, for two reasons.
            #
            # `objects` is tenant-strict: outside a request that has set
            # thread-local tenant context -- a management command, a Celery
            # task, this generator -- it matches nothing and the lookup raises
            # DoesNotExist for a branch that plainly exists.
            #
            # And a bare pk lookup on a UUID is unscoped: a branch id belonging
            # to another tenant would resolve, and the transfer would be raised
            # against it. Naming the tenant makes a cross-tenant id a clean
            # DoesNotExist instead, which is the same not-found behaviour the
            # caller already handles.
            src_branch = BranchLocation.all_objects.get(
                pk=item["source_branch_id"], tenant=ctx.tenant
            )
            dest_branch = BranchLocation.all_objects.get(
                pk=item["dest_branch_id"], tenant=ctx.tenant
            )

            transfer = StockTransferService.request_transfer(
                tenant=ctx.tenant,
                transfer_number=ref_str,
                source_branch=src_branch,
                dest_branch=dest_branch,
                source_location=item["source_location"],
                dest_location=item["dest_location"],
                requested_by=requester,
                lines_data=[{"sku": item["sku"], "quantity": item["quantity"]}],
                reason=f"Stage 2C replenishment transfer {ref_str}",
            )

            outcome = item["outcome"]

            if outcome == "REJECTED":
                StockTransferService.reject_transfer(
                    transfer=transfer, actor=approver, reason="Quality review transfer rejection"
                )
            elif outcome == "CANCELLED":
                StockTransferService.cancel_transfer(
                    transfer=transfer, actor=requester, reason="Transfer cancelled by requester"
                )
            else:
                # COMPLETED path: Approve -> Dispatch -> Receive
                StockTransferService.approve_transfer(transfer=transfer, approver=approver)
                StockTransferService.allocate_and_dispatch(transfer=transfer, dispatcher=requester)

                # Receive dispatched batches
                lines = list(StockTransferLine.all_objects.filter(transfer=transfer))
                received_data = []
                for line in lines:
                    dispatched_entries = InventoryLedgerEntry.all_objects.filter(
                        tenant=ctx.tenant,
                        source_document_type="STOCK_TRANSFER",
                        source_document_id=str(transfer.pk),
                        source_line_id=str(line.pk),
                        entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT,
                    ).select_related("inventory_batch")

                    for entry in dispatched_entries:
                        received_data.append({
                            "line_id": line.pk,
                            "batch_id": entry.inventory_batch_id,
                            "quantity": abs(entry.quantity_delta),
                            "damaged": Decimal("0"),
                        })

                if received_data:
                    StockTransferService.receive_transfer(
                        transfer=transfer,
                        receiver=receiver,
                        received_lines_data=received_data,
                        idempotency_key=f"recv-{ref_str}",
                    )

            ctx.own(transfer, domain="transfers", stage=self.id,
                    story_id=STORY_MOBILITY, reference=reference,
                    branch_reference=src_branch.code,
                    purpose=f"Stock transfer {ref_str} ({outcome})",
                    relationship_group=f"{REF}-MOBILITY", reset_eligible=False)
            ctx.add_count("stock_transfers", 1)
            ctx.add_count(f"stock_transfers.{transfer.status}", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# U1 — reservation planning
# ---------------------------------------------------------------------------


class StageU1ReservationPlanning(Stage):
    id = "U1"
    label = "Inventory reservation planning"
    requires = ("T2",)

    def rehydrate(self, ctx):
        StageT1TransferPlanning().run(ctx)

    def run(self, ctx):
        rnd = syn.rng(ctx.seed, "stage2c-reservation-planning")
        balances = list(_scenario_balances(ctx))

        if not balances:
            ctx.put("mobility:reservation_plan", [])
            return

        planned_reservations = []
        res_seq = 1

        # Target: 180 reservations across available balances
        # Outcome distribution: ~80% ALLOCATED/FULFILLED, ~10% EXPIRED, ~10% RELEASED
        for _ in range(180):
            bal = rnd.choice(balances)
            qty = max(Decimal("1"), Decimal(str(rnd.randint(1, min(10, int(bal.available) or 1)))))

            roll = rnd.random()
            if roll < 0.80:
                outcome = "ALLOCATED"
            elif roll < 0.90:
                outcome = "EXPIRED"
            else:
                outcome = "RELEASED"

            key = f"RES-{ctx.as_of.strftime('%Y%m%d')}-{res_seq:04d}"
            res_seq += 1

            planned_reservations.append({
                "idempotency_key": key,
                "branch": bal.branch,
                "location": bal.location,
                "sku": bal.sku,
                "quantity": qty,
                "purpose": f"Demo reservation {key}",
                "outcome": outcome,
            })

        ctx.put("mobility:reservation_plan", planned_reservations)
        ctx.add_count("reservations_planned", len(planned_reservations))


# ---------------------------------------------------------------------------
# U2 — inventory reservations execution
# ---------------------------------------------------------------------------


class StageU2InventoryReservations(Stage):
    id = "U2"
    label = "Inventory reservation execution"
    requires = ("U1",)

    def rehydrate(self, ctx):
        StageU1ReservationPlanning().run(ctx)

    def run(self, ctx):
        actor = ctx.get("user:ops")
        planned = ctx.get("mobility:reservation_plan") or []

        for item in planned:
            key = item["idempotency_key"]
            reference = f"{REF}-RES-{key}"

            if ctx.owned_reference(InventoryReservation, reference) is not None or InventoryReservation.all_objects.filter(
                tenant=ctx.tenant, idempotency_key=key
            ).exists():
                ctx.note_reuse("reservations", reference)
                ctx.add_count("inventory_reservations", 1)
                continue

            res = InventoryReservationService.reserve_stock(
                tenant=ctx.tenant,
                branch=item["branch"],
                source_location=item["location"],
                sku=item["sku"],
                requested_quantity=item["quantity"],
                purpose=item["purpose"],
                actor=actor,
                idempotency_key=key,
                expiry_time=ctx.as_of,
            )

            outcome = item["outcome"]
            if outcome == "EXPIRED":
                InventoryReservationService.expire_reservation(reservation=res, actor=actor)
            elif outcome == "RELEASED":
                InventoryReservationService.release_reservation(reservation=res, actor=actor)

            ctx.own(res, domain="reservations", stage=self.id,
                    story_id=STORY_MOBILITY, reference=reference,
                    branch_reference=item["branch"].code,
                    purpose=f"Reservation {key} ({res.status})",
                    relationship_group=f"{REF}-MOBILITY", reset_eligible=False)
            ctx.add_count("inventory_reservations", 1)
            ctx.add_count(f"inventory_reservations.{res.status}", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# V1 — balance rebuild
# ---------------------------------------------------------------------------


class StageV1BalanceRebuild(Stage):
    id = "V1"
    label = "Inventory mobility balance rebuild"
    requires = ("U2",)

    def rehydrate(self, ctx):
        pass

    def run(self, ctx):
        InventoryBalanceService.rebuild_all_balances(tenant=ctx.tenant)
        balance_count = InventoryBalance.all_objects.filter(tenant=ctx.tenant).count()
        ctx.add_count("inventory_balances_rebuilt_mobility", balance_count)


# ---------------------------------------------------------------------------
# V2 — mobility boundary check
# ---------------------------------------------------------------------------


class StageV2MobilityBoundaryCheck(Stage):
    id = "V2"
    label = "Inventory mobility boundary verification"
    requires = ("V1",)

    def rehydrate(self, ctx):
        pass

    def run(self, ctx):
        # 1. Total TRANSFER_OUT quantity equals total TRANSFER_IN quantity
        transfer_out = abs(
            InventoryLedgerEntry.all_objects.filter(
                tenant=ctx.tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT
            ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")
        )
        transfer_in = InventoryLedgerEntry.all_objects.filter(
            tenant=ctx.tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN
        ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")

        if transfer_out != transfer_in:
            raise ValidationError(
                f"Transfer ledger imbalance: TRANSFER_OUT ({transfer_out}) != TRANSFER_IN ({transfer_in})."
            )

        # 2. Rebuild balances and assert zero drift
        before = InventoryBalance.all_objects.filter(tenant=ctx.tenant).aggregate(s=Sum("on_hand"))["s"] or Decimal("0")
        InventoryBalanceService.rebuild_all_balances(tenant=ctx.tenant)
        after = InventoryBalance.all_objects.filter(tenant=ctx.tenant).aggregate(s=Sum("on_hand"))["s"] or Decimal("0")

        if before != after:
            raise ValidationError(f"Mobility balance rebuild drift: before {before}, after {after}.")

        # 3. Assert zero negative stock
        if InventoryBalance.all_objects.filter(tenant=ctx.tenant, on_hand__lt=0).exists():
            raise ValidationError("Negative on_hand balance detected.")

        ctx.add_count("mobility_boundary_verified", 1)


STAGE_2C: tuple[Stage, ...] = (
    StageT1TransferPlanning(),
    StageT2StockTransfers(),
    StageU1ReservationPlanning(),
    StageU2InventoryReservations(),
    StageV1BalanceRebuild(),
    StageV2MobilityBoundaryCheck(),
)
