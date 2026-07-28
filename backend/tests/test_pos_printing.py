"""Durable receipt document and print-job regression tests."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    domain,
    make_clinically_ready,
    setup_domain,
)

from apps.prescription.pos_dispensing_services import (
    PosDispensingQueueService,
    PosPaymentOrchestrationService,
)
from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
from apps.prescription.pos_printing_services import PosPrintJobService


pytestmark = pytest.mark.django_db


def settle_episode(domain):
    episode = domain["episode"]
    make_clinically_ready(domain)
    PosDispensingQueueService.transition_state(
        episode=episode,
        new_status="CHECKING",
        actor=domain["pharmacist"],
    )
    episode.refresh_from_db()
    PosDispensingQueueService.transition_state(
        episode=episode,
        new_status="READY_FOR_PAYMENT",
        actor=domain["pharmacist"],
    )
    episode.refresh_from_db()
    result = PosPaymentOrchestrationService.process_payment(
        episode=episode,
        tender_type="CASH",
        paid_amount=Decimal("500.00"),
        cashier=domain["cashier"],
        idempotency_key="PRINT-PAYMENT-1",
        device_id=domain["device_id"],
    )
    episode.refresh_from_db()
    return episode, result


def test_settlement_creates_one_immutable_receipt_snapshot_and_job(domain):
    episode, result = settle_episode(domain)
    document = PosPrintDocument.all_objects.get(episode=episode)
    job = PosPrintJob.all_objects.get(document=document)

    assert result["receipt"]["document_number"] == document.document_number
    assert result["receipt"]["print_job_id"] == str(job.id)
    assert job.status == PosPrintJob.Status.QUEUED
    assert document.snapshot["payment"]["amount_due"] == "150.00"
    assert document.snapshot["patient"]["name"] == "John Doe"

    replay = PosPaymentOrchestrationService.process_payment(
        episode=episode,
        tender_type="CASH",
        paid_amount=Decimal("500.00"),
        cashier=domain["cashier"],
        idempotency_key="PRINT-PAYMENT-1",
        device_id=domain["device_id"],
    )
    assert replay["replayed"] is True
    assert PosPrintDocument.all_objects.filter(episode=episode).count() == 1
    assert PosPrintJob.all_objects.filter(document=document).count() == 1


def test_print_transport_failure_does_not_reverse_settlement(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)

    PosPrintJobService.start_attempt(job=job, actor=domain["pharmacist"])
    PosPrintJobService.record_result(
        job=job,
        actor=domain["pharmacist"],
        succeeded=False,
        failure_code="PAPER_OUT",
        failure_message="Printer is out of paper.",
    )

    job.refresh_from_db()
    episode.refresh_from_db()
    assert job.status == PosPrintJob.Status.RETRY_REQUIRED
    assert episode.payment_state == "PAID"
    assert episode.status == "PAID"


def test_retry_uses_the_existing_job_and_records_a_single_success(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)

    PosPrintJobService.start_attempt(job=job, actor=domain["pharmacist"])
    PosPrintJobService.record_result(
        job=job,
        actor=domain["pharmacist"],
        succeeded=False,
        failure_code="JAM",
        failure_message="Receipt jammed.",
    )
    PosPrintJobService.retry(job=job, actor=domain["pharmacist"])
    PosPrintJobService.start_attempt(job=job, actor=domain["pharmacist"])
    completed = PosPrintJobService.record_result(
        job=job,
        actor=domain["pharmacist"],
        succeeded=True,
    )

    assert completed.id == job.id
    assert completed.status == PosPrintJob.Status.PRINTED
    assert completed.attempt_count == 2
    assert PosPrintJob.all_objects.filter(document=job.document).count() == 1


def test_render_and_cancellation_are_durable_and_accountable(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)

    assert job.branch_id == episode.branch_id
    assert job.device_id == domain["device_id"]

    rendered = PosPrintJobService.mark_rendered(job=job, actor=domain["pharmacist"])
    assert rendered.status == PosPrintJob.Status.RENDERED

    cancelled = PosPrintJobService.cancel(
        job=rendered,
        actor=domain["pharmacist"],
        reason="Printer maintenance started before transport dispatch.",
    )
    assert cancelled.status == PosPrintJob.Status.CANCELLED
    assert cancelled.cancelled_by_id == domain["pharmacist"].id
    assert cancelled.cancellation_reason == "Printer maintenance started before transport dispatch."

    with pytest.raises(ValidationError, match="cannot be sent"):
        PosPrintJobService.start_attempt(job=cancelled, actor=domain["pharmacist"])


def test_reprint_requires_a_confirmed_original_and_reason(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)

    with pytest.raises(ValidationError, match="only after its original print"):
        PosPrintJobService.request_reprint(
            document=job.document,
            actor=domain["pharmacist"],
            reason="Patient requested another copy.",
        )

    PosPrintJobService.start_attempt(job=job, actor=domain["pharmacist"])
    PosPrintJobService.record_result(job=job, actor=domain["pharmacist"], succeeded=True)
    with pytest.raises(ValidationError, match="requires a stated reason"):
        PosPrintJobService.request_reprint(
            document=job.document,
            actor=domain["pharmacist"],
            reason="",
        )

    reprint = PosPrintJobService.request_reprint(
        document=job.document,
        actor=domain["pharmacist"],
        reason="Original receipt was damaged.",
    )
    assert reprint.copy_classification == PosPrintJob.CopyClassification.REPRINT
    assert reprint.copy_number == 2
    assert reprint.reprint_reason == "Original receipt was damaged."


def test_cashier_cannot_claim_a_print_job(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)

    with pytest.raises(PermissionDenied):
        PosPrintJobService.start_attempt(job=job, actor=domain["cashier"])


def test_print_document_snapshot_cannot_be_changed(domain):
    episode, _ = settle_episode(domain)
    document = PosPrintDocument.all_objects.get(episode=episode)
    document.snapshot["payment"]["amount_due"] = "1.00"

    with pytest.raises(ValueError, match="immutable"):
        document.save()
