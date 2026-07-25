"""Label printing and reprint governance.

A dispensing label is the instruction a patient takes home, so a second copy in
circulation is a real hazard: two labels for one supply can end up on two packs,
or an old label can outlive the supply it described.

The rules here:

1. The first successful print of a label is the original. Every later print is a
   reprint, needs a reason, and needs the capability. That distinction is
   recorded, not inferred at read time.
2. A label for a supply that was reversed or cancelled cannot be reprinted at
   all. A valid-looking label for medicine that was never handed over is worse
   than no label.
3. Failed prints are recorded too. A printer that jams three times and succeeds
   once has produced one label, and the audit has to show that.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.prescription.models import DispensingLabel, PosLabelReprintAudit
from apps.prescription.services.clinical_dispensing import _require_capability
from apps.workflows.service import emit_event

#: Episode states in which a label must not be printed or reprinted. A label is
#: a claim that this medicine was supplied as described.
NON_PRINTABLE_EPISODE_STATES = frozenset({"CANCELLED", "REJECTED", "REVERSED", "RETURNED"})


class LabelPrintService:
    @staticmethod
    def print_count(*, label) -> int:
        """Successful prints so far. Zero means nothing has been printed."""
        return PosLabelReprintAudit.all_objects.filter(label=label, status="SUCCEEDED").count()

    @staticmethod
    def is_original(*, label) -> bool:
        return LabelPrintService.print_count(label=label) == 0

    @staticmethod
    @transaction.atomic
    def record_print(
        *,
        label,
        actor,
        printer="",
        reason="",
        succeeded=True,
        failure_reason="",
    ):
        """Record a print attempt against a label.

        The first success is the original and needs no reason. Anything after it
        is a reprint: it requires the reprint capability and a stated reason,
        because a second label in circulation has to be explainable.
        """
        label = DispensingLabel.all_objects.select_for_update().get(pk=label.pk)
        episode = label.episode

        if episode.status in NON_PRINTABLE_EPISODE_STATES:
            raise ValidationError(
                f"Episode is {episode.status}; a label must not be printed for a supply "
                "that was not completed."
            )

        original = LabelPrintService.is_original(label=label)

        if original:
            _require_capability(actor, label.tenant_id, "pos.label.print")
        else:
            # Deliberately a distinct capability: routinely printing labels is
            # not the same authority as producing a duplicate.
            _require_capability(actor, label.tenant_id, "pos.label.reprint")
            if not reason.strip():
                raise ValidationError("A reprint requires a stated reason.")

        record = PosLabelReprintAudit.all_objects.create(
            tenant_id=label.tenant_id,
            label=label,
            reprinted_by=actor,
            reprint_reason=reason.strip(),
            reprinted_at=timezone.now(),
            is_original=original,
            printer=printer,
            status="SUCCEEDED" if succeeded else "FAILED",
            failure_reason=failure_reason,
        )

        emit_event(
            tenant_id=str(label.tenant_id),
            aggregate_type="DispensingLabel",
            aggregate_id=str(label.pk),
            event_type="LabelPrinted" if original else "LabelReprinted",
            payload={
                "label_id": str(label.pk),
                "episode_id": str(episode.pk),
                "document_number": label.document_number,
                "is_original": original,
                "succeeded": succeeded,
                "reason": reason,
                "printer": printer,
                "actor_id": str(actor.pk) if actor else "",
            },
        )
        return record

    @staticmethod
    def history(*, label):
        """Print history, oldest first, for the episode timeline."""
        return list(
            PosLabelReprintAudit.all_objects.filter(label=label).order_by("reprinted_at")
        )
