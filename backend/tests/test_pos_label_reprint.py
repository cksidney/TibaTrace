"""Label printing and reprint governance.

A dispensing label is the instruction a patient takes home. A second copy in
circulation can end up on the wrong pack, or outlive the supply it described, so
producing one is a governed act rather than a convenience.

PosLabelReprintAudit existed since 138e539 but nothing ever wrote to it.
"""
import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.prescription.label_printing import LabelPrintService
from apps.prescription.models import DispensingLabel, PosLabelReprintAudit

pytestmark = pytest.mark.django_db


@pytest.fixture
def label(domain):  # noqa: F811
    return DispensingLabel.all_objects.create(
        tenant=domain["tenant"],
        episode=domain["episode"],
        dispensing_line=domain["line"],
        document_number="LBL-0001",
        content={"medicine": "Panadol 500mg", "directions": "Take one three times a day"},
        document_hash="0" * 64,
        barcode_payload="LBL-0001",
        generated_by=domain["pharmacist"],
    )


def test_first_print_is_the_original(domain, label):  # noqa: F811
    assert LabelPrintService.is_original(label=label) is True
    record = LabelPrintService.record_print(
        label=label, actor=domain["pharmacist"], printer="LABEL-1"
    )
    assert record.is_original is True
    assert record.status == "SUCCEEDED"
    assert LabelPrintService.is_original(label=label) is False


def test_the_original_needs_no_reason(domain, label):  # noqa: F811
    record = LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    assert record.reprint_reason == ""


def test_every_later_print_is_a_reprint_and_needs_a_reason(domain, label):  # noqa: F811
    LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    with pytest.raises(ValidationError, match="reprint requires a stated reason"):
        LabelPrintService.record_print(label=label, actor=domain["pharmacist"])


def test_reprint_with_a_reason_is_recorded_as_a_reprint(domain, label):  # noqa: F811
    LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    reprint = LabelPrintService.record_print(
        label=label, actor=domain["pharmacist"], reason="Label smudged in the printer"
    )
    assert reprint.is_original is False
    assert reprint.reprint_reason == "Label smudged in the printer"
    assert PosLabelReprintAudit.all_objects.filter(label=label).count() == 2


def test_a_cashier_cannot_reprint(domain, label):  # noqa: F811
    """Printing routinely is not the same authority as producing a duplicate."""
    LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    with pytest.raises(PermissionDenied):
        LabelPrintService.record_print(
            label=label, actor=domain["cashier"], reason="wants another copy"
        )


def test_printing_is_refused_for_a_cancelled_episode(domain, label):  # noqa: F811
    """A valid-looking label for medicine never handed over is worse than none."""
    episode = domain["episode"]
    episode.status = "CANCELLED"
    episode.save(update_fields=["status"])

    with pytest.raises(ValidationError, match="must not be printed"):
        LabelPrintService.record_print(label=label, actor=domain["pharmacist"])


@pytest.mark.parametrize("state", ["CANCELLED", "REJECTED", "REVERSED", "RETURNED"])
def test_printing_is_refused_for_every_non_supplied_state(domain, label, state):  # noqa: F811
    episode = domain["episode"]
    episode.status = state
    episode.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        LabelPrintService.record_print(label=label, actor=domain["pharmacist"])


def test_a_failed_print_does_not_consume_the_original(domain, label):  # noqa: F811
    """A jam is not a label. The next attempt is still the original."""
    LabelPrintService.record_print(
        label=label,
        actor=domain["pharmacist"],
        succeeded=False,
        failure_reason="Printer out of media",
    )
    assert LabelPrintService.is_original(label=label) is True

    record = LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    assert record.is_original is True


def test_failed_attempts_are_retained_in_the_audit(domain, label):  # noqa: F811
    LabelPrintService.record_print(
        label=label, actor=domain["pharmacist"], succeeded=False, failure_reason="Jam"
    )
    LabelPrintService.record_print(label=label, actor=domain["pharmacist"])

    history = LabelPrintService.history(label=label)
    assert len(history) == 2
    assert [record.status for record in history] == ["FAILED", "SUCCEEDED"]


def test_originality_is_recorded_not_inferred(domain, label):  # noqa: F811
    """Deriving it from a count breaks once a failure sits between prints."""
    first = LabelPrintService.record_print(label=label, actor=domain["pharmacist"])
    LabelPrintService.record_print(
        label=label, actor=domain["pharmacist"], succeeded=False, failure_reason="Jam", reason="retry"
    )
    second = LabelPrintService.record_print(
        label=label, actor=domain["pharmacist"], reason="Patient lost the first"
    )

    assert first.is_original is True
    assert second.is_original is False
