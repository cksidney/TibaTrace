"""Stage 2B.2A — quality inspection and quality decisions.

Records what quality concluded about each of the received batches, and **moves
nothing**. No release, no posting, no ledger entry, no balance.

The point of the increment is to prove that quality review exists independently
of stock release. Until this stage, the two were the same event: the only way
to record a `QualityDecision` was `release_quarantined_batch`, which released.
So there was no state in which stock had been assessed but not yet handed to
the shelf -- and therefore no way to say "quality looked at this and held it".

Five checkpoints. The planning stages are not filler: they compute the outcome
distribution and put it in the registry before anything is written, so the plan
is auditable on its own and a resume recomputes it identically rather than
inferring it from whatever happens to exist.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError

from apps.procurement.models import (
    GoodsReceipt,
    QualityDecision,
    ReceivedBatch,
    ReceivingInspection,
)
from apps.procurement.services.batch_quality_service import BatchQualityDecisionService
from apps.procurement.services.quality_service import QualityService

from . import synthetic as syn
from .stages import REF, Stage

STORY_QUALITY = "NC-OPS-QUALITY-001"

Outcome = QualityDecision.Outcome

#: Target distribution over the received batches. Sums to 1.0; the planner
#: converts to counts and reconciles the remainder onto approvals, so the
#: totals always add to exactly the batch count.
OUTCOME_WEIGHTS = (
    (Outcome.APPROVE_FOR_RELEASE, 0.803),
    (Outcome.HOLD_FOR_REVIEW, 0.065),
    (Outcome.REJECT, 0.037),
    (Outcome.DAMAGE_HOLD, 0.028),
    (Outcome.TEMPERATURE_EXCURSION, 0.028),
    (Outcome.NEAR_EXPIRY_HOLD, 0.021),
    (Outcome.DOCUMENTATION_HOLD, 0.018),
)

#: Shelf life below which a batch is a near-expiry candidate.
NEAR_EXPIRY_DAYS = 120

REASONS = {
    Outcome.APPROVE_FOR_RELEASE:
        "Packaging intact, batch and expiry match the delivery note, quantity agrees.",
    Outcome.HOLD_FOR_REVIEW:
        "Minor discrepancy against the delivery note; held pending supplier response.",
    Outcome.REJECT:
        "Packaging integrity failure on arrival; refused and retained for disposition.",
    Outcome.DAMAGE_HOLD:
        "Outer carton crushed in transit; held for damage assessment.",
    Outcome.TEMPERATURE_EXCURSION:
        "Cold-chain excursion logged on arrival; held pending stability review.",
    Outcome.NEAR_EXPIRY_HOLD:
        "Short remaining shelf life; held pending formulary policy review.",
    Outcome.DOCUMENTATION_HOLD:
        "Batch certificate not supplied with the delivery; held pending documents.",
}


def _scenario_batches(ctx):
    """Every received batch this scenario owns, ordered deterministically.

    Ordered by batch number rather than primary key: a "deterministic"
    distribution that depended on insertion order would shift the moment a
    batch was added.
    """
    return list(
        ReceivedBatch.all_objects.filter(tenant=ctx.tenant)
        .select_related(
            "grn_line__goods_receipt",
            "sku__manufactured_product__clinical_product__dose_form",
        )
        .order_by("manufacturer_batch_number")
    )


def _is_cold_chain_batch(batch) -> bool:
    from apps.medicines.provisioning import _is_cold_chain

    return _is_cold_chain(batch.sku) or bool(batch.temperature_excursion)


# ---------------------------------------------------------------------------
# O1 — inspection planning
# ---------------------------------------------------------------------------


class StageO1InspectionPlan(Stage):
    id = "O1"
    label = "Quality inspection planning"

    def run(self, ctx):
        receipts = list(
            GoodsReceipt.all_objects.filter(tenant=ctx.tenant).order_by("grn_number")
        )
        ctx.put("quality:receipts", receipts)
        ctx.add_count("receipts_to_inspect", len(receipts))

    def rehydrate(self, ctx):
        self.run(ctx)


# ---------------------------------------------------------------------------
# O2 — inspections
# ---------------------------------------------------------------------------


class StageO2Inspections(Stage):
    id = "O2"
    label = "Quality inspections"
    requires = ("O1",)

    def rehydrate(self, ctx):
        StageO1InspectionPlan().run(ctx)

    def run(self, ctx):
        # The receiver may not inspect their own delivery, so the quality
        # officer does. Stage 2A created both.
        inspector = ctx.get("user:quality")

        for receipt in ctx.get("quality:receipts"):
            reference = f"{REF}-INSPECTION-{receipt.grn_number}"
            if ctx.owned_reference(ReceivingInspection, reference) is not None:
                ctx.note_reuse("quality_inspections", reference)
                ctx.add_count("quality_inspections", 1)
                continue
            if receipt.received_by_id == inspector.pk:
                raise PermissionDenied(
                    f"{receipt.grn_number} was received by the inspector; quality "
                    "review must be independent of receiving."
                )

            # QUARANTINE only. REJECT and DESTROY set rejected_quantity and zero
            # quarantined_quantity -- they move stock, which this increment must
            # not do. Per-batch rejection is recorded as a decision in P2, where
            # it moves nothing.
            inspection = QualityService.record_inspection(
                goods_receipt=receipt,
                inspector=inspector,
                decision=ReceivingInspection.Decision.QUARANTINE,
                notes=(
                    "Delivery inspected on arrival: packaging, batch and expiry "
                    "checked against the delivery note. Held pending per-batch "
                    "quality decisions."
                ),
            )
            ctx.own(inspection, domain="quality_inspections", stage=self.id,
                    story_id=STORY_QUALITY, reference=reference,
                    branch_reference=receipt.receiving_branch.code,
                    purpose=f"Arrival inspection of {receipt.grn_number}.",
                    relationship_group=f"{REF}-QUALITY", reset_eligible=False)
            ctx.add_count("quality_inspections", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# P1 — decision planning
# ---------------------------------------------------------------------------


class StageP1DecisionPlan(Stage):
    id = "P1"
    label = "Quality decision planning"
    requires = ("O2",)

    def rehydrate(self, ctx):
        self.run(ctx)

    def run(self, ctx):
        batches = _scenario_batches(ctx)
        plan = self.plan_outcomes(ctx, batches)
        ctx.put("quality:plan", plan)
        ctx.put("quality:batches", batches)
        for outcome in plan.values():
            ctx.add_count(f"quality_planned.{outcome}", 1)
        ctx.add_count("batches_planned", len(plan))

    @staticmethod
    def plan_outcomes(ctx, batches) -> dict[str, str]:
        """Assign every batch an outcome, deterministically and exactly.

        Two constraints make this more than a weighted draw:

        * An expired batch can never be approved -- approval is what a later
          release keys off.
        * TEMPERATURE_EXCURSION only means anything on a temperature-sensitive
          line, and the service refuses it elsewhere.

        So constrained batches are assigned first from the pool they are
        eligible for, and the remainder is reconciled onto approvals. The
        counts therefore always sum to the batch count rather than
        approximately so.
        """
        total = len(batches)
        if not total:
            return {}

        # Rank by a stable hash so the assignment does not depend on the order
        # the database returned rows in.
        ordered = sorted(
            batches,
            key=lambda b: syn.stable_int(ctx.seed, "quality", b.manufacturer_batch_number),
        )

        targets: dict[str, int] = {}
        for outcome, weight in OUTCOME_WEIGHTS[1:]:
            targets[outcome] = max(1, round(total * weight))
        # Approvals absorb the remainder, so the total reconciles exactly.
        targets[Outcome.APPROVE_FOR_RELEASE] = total - sum(targets.values())

        plan: dict[str, str] = {}
        remaining = dict(targets)

        cold_chain = [b for b in ordered if _is_cold_chain_batch(b)]
        expired = [b for b in ordered if b.expiry_date <= ctx.as_of]
        near_expiry = [
            b for b in ordered
            if 0 < (b.expiry_date - ctx.as_of).days <= NEAR_EXPIRY_DAYS
        ]

        def assign(batch, outcome):
            if batch.pk in plan or remaining.get(outcome, 0) <= 0:
                return False
            plan[batch.pk] = outcome
            remaining[outcome] -= 1
            return True

        # Constrained outcomes first, from their eligible pools.
        for batch in cold_chain:
            assign(batch, Outcome.TEMPERATURE_EXCURSION)
        for batch in near_expiry:
            assign(batch, Outcome.NEAR_EXPIRY_HOLD)
        # An expired batch cannot be approved; reject or hold it instead.
        for batch in expired:
            if not assign(batch, Outcome.REJECT):
                assign(batch, Outcome.HOLD_FOR_REVIEW)
            plan.setdefault(batch.pk, Outcome.HOLD_FOR_REVIEW)

        # Everything else, in hash order, filling the remaining quotas.
        fill_order = [
            Outcome.HOLD_FOR_REVIEW, Outcome.REJECT, Outcome.DAMAGE_HOLD,
            Outcome.DOCUMENTATION_HOLD, Outcome.TEMPERATURE_EXCURSION,
            Outcome.NEAR_EXPIRY_HOLD,
        ]
        for batch in ordered:
            if batch.pk in plan:
                continue
            for outcome in fill_order:
                if outcome == Outcome.TEMPERATURE_EXCURSION and not _is_cold_chain_batch(batch):
                    continue
                if assign(batch, outcome):
                    break
            else:
                plan[batch.pk] = Outcome.APPROVE_FOR_RELEASE

        # Anything still unassigned is an approval, unless it has expired.
        for batch in ordered:
            if batch.pk not in plan:
                plan[batch.pk] = (
                    Outcome.HOLD_FOR_REVIEW if batch.expiry_date <= ctx.as_of
                    else Outcome.APPROVE_FOR_RELEASE
                )
        return plan


# ---------------------------------------------------------------------------
# P2 — decisions
# ---------------------------------------------------------------------------


class StageP2Decisions(Stage):
    id = "P2"
    label = "Quality decisions"
    requires = ("P1",)

    def rehydrate(self, ctx):
        StageP1DecisionPlan().run(ctx)

    def run(self, ctx):
        inspector = ctx.get("user:quality")
        # A different person signs the decision off. The service refuses the
        # receiver for either role; using a third actor also demonstrates the
        # inspector/approver split the domain supports.
        approver = ctx.get("user:ops")
        plan = ctx.get("quality:plan")

        for batch in ctx.get("quality:batches"):
            outcome = plan.get(batch.pk)
            if outcome is None:
                continue
            reference = f"{REF}-QD-{batch.manufacturer_batch_number}"
            if ctx.owned_reference(QualityDecision, reference) is not None:
                ctx.note_reuse("quality_decisions", reference)
                ctx.add_count("quality_decisions", 1)
                ctx.add_count(f"quality_decisions.{outcome}", 1)
                continue

            decision = BatchQualityDecisionService.record_decision(
                batch=batch,
                inspector=inspector,
                decision_by=approver,
                outcome=outcome,
                reason=REASONS[outcome],
                evidence_reference=f"{reference}-EVIDENCE",
                as_of=ctx.as_of,
                requires_cold_chain=_is_cold_chain_batch(batch),
            )
            ctx.own(decision, domain="quality_decisions", stage=self.id,
                    story_id=STORY_QUALITY, reference=reference,
                    branch_reference=batch.grn_line.goods_receipt.receiving_branch.code,
                    purpose=f"{outcome} for {batch.manufacturer_batch_number}.",
                    relationship_group=f"{REF}-QUALITY", reset_eligible=False)
            ctx.add_count("quality_decisions", 1)
            ctx.add_count(f"quality_decisions.{outcome}", 1)
            ctx.stage_results[self.id].last_key = reference


# ---------------------------------------------------------------------------
# P3 — boundary verification
# ---------------------------------------------------------------------------


class StageP3BoundaryCheck(Stage):
    id = "P3"
    label = "Quality boundary verification"
    requires = ("P2",)

    def rehydrate(self, ctx):
        StageP1DecisionPlan().run(ctx)

    def run(self, ctx):
        """Assert the boundary rather than trust it.

        Recording a decision must have moved nothing. If it did, the failure is
        that stock became available without a release, which no count in the
        summary would reveal.
        """
        from django.db.models import F

        from apps.inventory.models import (
            InventoryBalance,
            InventoryBatch,
            InventoryLedgerEntry,
        )

        batches = ReceivedBatch.all_objects.filter(tenant=ctx.tenant)
        released = batches.filter(
            quality_status=ReceivedBatch.QualityStatus.RELEASED
        ).count()
        accepted = batches.filter(accepted_quantity__gt=0).count()
        unheld = batches.exclude(quarantined_quantity=F("received_quantity")).count()
        problems = []
        if released:
            problems.append(f"{released} released")
        if accepted:
            problems.append(f"{accepted} with accepted units")
        if unheld:
            problems.append(f"{unheld} not fully quarantined")
        for label, model in (
            ("ledger entries", InventoryLedgerEntry),
            ("balances", InventoryBalance),
            ("inventory batches", InventoryBatch),
        ):
            count = model.all_objects.filter(tenant=ctx.tenant).count()
            if count:
                problems.append(f"{count} {label}")
        if problems:
            raise ValidationError(
                "Stage 2B.2A records decisions and moves nothing, but found: "
                + "; ".join(problems)
                + ". Release and posting are Stage 2B.2B."
            )

        undecided = batches.count() - QualityDecision.all_objects.filter(
            tenant=ctx.tenant
        ).count()
        if undecided:
            raise ValidationError(f"{undecided} batch(es) have no quality decision.")
        ctx.add_count("boundary_verified", 1)


STAGE_2B_2A: tuple[Stage, ...] = (
    StageO1InspectionPlan(),
    StageO2Inspections(),
    StageP1DecisionPlan(),
    StageP2Decisions(),
    StageP3BoundaryCheck(),
)
