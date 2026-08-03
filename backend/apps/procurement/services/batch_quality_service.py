"""Per-batch quality decisions.

`QualityService.record_inspection` is per *goods receipt*: it applies one
decision to every batch under it. Real deliveries are not uniform -- one
crushed carton on a pallet is the normal case -- so a per-receipt verdict
cannot describe what actually arrived.

`QualityService.release_quarantined_batch` is per batch, but despite the name
it sets `quality_status` to RELEASED. It was the only way to record a
`QualityDecision`, which meant reviewing a batch and releasing it were the same
event and neither could happen without the other.

This service separates them. Recording a decision moves **no quantity** and
never sets RELEASED. A batch approved here is *eligible* for release; the
release itself is a later, separate act by `release_batch`.

That separation is the control. A decision that released as a side effect would
make "reviewed" and "available" indistinguishable, and there would be no state
in which stock had been assessed but not yet handed to the shelf.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.procurement.models import QualityDecision, ReceivedBatch
from apps.workflows.service import emit_event

Outcome = QualityDecision.Outcome

#: Quality review here is internal document and physical inspection. Nothing
#: contacts the PPB or any registry, so nothing may record that it did.
MANUAL_QUALITY_REVIEW = "MANUAL_INTERNAL_QUALITY_REVIEW"

#: Batch states a decision may be recorded against. A released or destroyed
#: batch has already left review.
REVIEWABLE_STATUSES = frozenset(
    {
        ReceivedBatch.QualityStatus.PENDING_INSPECTION,
        ReceivedBatch.QualityStatus.QUARANTINED,
    }
)

#: Outcomes that require the batch to be temperature-sensitive to make sense.
COLD_CHAIN_ONLY_OUTCOMES = frozenset({Outcome.TEMPERATURE_EXCURSION})


class BatchQualityDecisionService:
    """Records what quality decided about one received batch."""

    @staticmethod
    @transaction.atomic
    def record_decision(
        *,
        batch: ReceivedBatch,
        inspector,
        decision_by,
        outcome: str,
        reason: str,
        evidence_reference: str = "",
        as_of: date | None = None,
        requires_cold_chain: bool = False,
    ) -> QualityDecision:
        """Record a quality outcome against a batch, moving nothing.

        Idempotent on (tenant, batch), matching the unique constraint: a batch
        has one decision, because a second would make "what did quality decide?"
        depend on which row was read first, and release keys off that answer.
        """
        if batch is None:
            raise ValidationError("A quality decision requires a batch.")
        if inspector is None:
            raise PermissionDenied("A quality decision requires a named inspector.")
        if decision_by is None:
            raise PermissionDenied("A quality decision requires a named decision maker.")
        if outcome not in Outcome.values:
            known = ", ".join(Outcome.values)
            raise ValidationError(f"Unknown quality outcome {outcome!r}. Known: {known}")
        if not str(reason or "").strip():
            raise ValidationError("A quality decision requires a reason.")

        receipt = batch.grn_line.goods_receipt

        # The person who booked the goods in may not also pass them. Receiving
        # and quality are the two halves of the control, and one person holding
        # both means the delivery is only ever checked by the person who
        # accepted it.
        if receipt.received_by_id and str(receipt.received_by_id) == str(inspector.pk):
            raise PermissionDenied(
                "The person who received the delivery cannot inspect it. Quality "
                "review must be independent of receiving."
            )
        if receipt.received_by_id and str(receipt.received_by_id) == str(decision_by.pk):
            raise PermissionDenied(
                "The person who received the delivery cannot sign off its quality "
                "decision."
            )

        if batch.quality_status not in REVIEWABLE_STATUSES:
            raise ValidationError(
                f"Batch {batch.manufacturer_batch_number} is {batch.quality_status} "
                "and is no longer in review."
            )

        as_of = as_of or timezone.localdate()

        # An expired batch cannot be approved. Approval is what a later release
        # keys off, so approving expired stock is how it reaches a shelf.
        if outcome == Outcome.APPROVE_FOR_RELEASE and batch.expiry_date <= as_of:
            raise ValidationError(
                f"Batch {batch.manufacturer_batch_number} expired on "
                f"{batch.expiry_date} and cannot be approved for release."
            )
        if outcome in COLD_CHAIN_ONLY_OUTCOMES and not (
            requires_cold_chain or batch.temperature_excursion
        ):
            raise ValidationError(
                f"{outcome} does not apply to {batch.manufacturer_batch_number}: it "
                "is not a temperature-sensitive line and no excursion was logged."
            )

        existing = QualityDecision.all_objects.filter(
            tenant=batch.tenant, batch=batch
        ).first()
        if existing is not None:
            if existing.decision != outcome:
                # Not overwritten. A recorded decision is evidence, and changing
                # it silently would rewrite what quality concluded.
                raise ValidationError(
                    f"Batch {batch.manufacturer_batch_number} already has a "
                    f"{existing.decision} decision. Recording {outcome} would "
                    "overwrite it; supersede it deliberately instead."
                )
            return existing

        decision = QualityDecision.all_objects.create(
            tenant=batch.tenant,
            goods_receipt=receipt,
            batch=batch,
            decision=outcome,
            decision_by=decision_by,
            inspector=inspector,
            decision_notes=reason,
            evidence_reference=evidence_reference,
            evidence_basis=MANUAL_QUALITY_REVIEW,
        )

        # Deliberately absent: no quantity change, no quality_status change, no
        # InventoryBatch, no ledger entry. The batch stays exactly as received.

        log_audit(
            tenant_id=batch.tenant_id,
            action="BATCH_QUALITY_DECISION_RECORDED",
            model_name="QualityDecision",
            object_id=decision.pk,
            actor_id=getattr(decision_by, "id", None),
            metadata={
                "batch": batch.manufacturer_batch_number,
                "outcome": outcome,
                "inspector": getattr(inspector, "username", ""),
                "evidence_basis": MANUAL_QUALITY_REVIEW,
            },
        )
        if batch.tenant_id:
            emit_event(
                tenant_id=batch.tenant_id,
                aggregate_type="BATCH_QUALITY",
                aggregate_id=str(batch.pk),
                event_type="BatchQualityDecisionRecorded",
                payload={"outcome": outcome, "reason": reason},
            )
        return decision

    @staticmethod
    def decision_for(*, batch: ReceivedBatch) -> QualityDecision | None:
        return QualityDecision.all_objects.filter(
            tenant=batch.tenant, batch=batch
        ).first()

    @staticmethod
    def is_releasable(*, batch: ReceivedBatch) -> bool:
        """Whether quality has cleared this batch for a later release.

        The question `release_batch` should be asking. It does not ask it today,
        which is why a batch can be released with no decision recorded at all.
        """
        decision = BatchQualityDecisionService.decision_for(batch=batch)
        return (
            decision is not None
            and decision.decision in QualityDecision.RELEASABLE_OUTCOMES
        )
