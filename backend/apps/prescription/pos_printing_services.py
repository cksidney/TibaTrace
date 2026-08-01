"""Authoritative POS document snapshots and print-job lifecycle services."""
from __future__ import annotations

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.money import format_money
from apps.prescription.models import DispensingLine
from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
from apps.prescription.services.clinical_dispensing import _require_capability
from apps.workflows.service import emit_event


def _hash_snapshot(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PosPrintDocumentService:
    @staticmethod
    def _receipt_snapshot(*, episode, settlement):
        tender = settlement.payment_tender
        intent = tender.payment_intent
        lines = list(
            DispensingLine.all_objects.filter(episode=episode)
            .select_related("supplied_sku", "prescribed_sku")
            .order_by("created_at")
        )
        patient_name = " ".join(
            value for value in [episode.patient.first_name, episode.patient.last_name] if value
        ).strip()
        return {
            "document_type": PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
            "document_number": f"RCP-{episode.dispensing_number}-{settlement.id.hex[:8].upper()}",
            "issued_at": settlement.settled_at.isoformat(),
            "tenant_id": str(episode.tenant_id),
            "branch_id": str(episode.branch_id),
            "episode_id": str(episode.id),
            "dispensing_number": episode.dispensing_number,
            "patient": {
                "id": str(episode.patient_id),
                "name": patient_name,
                "number": getattr(episode.patient, "patient_number", ""),
            },
            "prescription_number": getattr(episode.prescription, "prescription_number", ""),
            "lines": [
                {
                    "line_id": str(line.id),
                    "medicine": getattr(line.supplied_sku or line.prescribed_sku, "display_name", ""),
                    "quantity": str(line.quantity_authorized),
                    "unit": line.unit,
                    "batch_number": line.batch_number_snapshot,
                }
                for line in lines
            ],
            "payment": {
                "settlement_id": str(settlement.id),
                "reference": settlement.provider_reference or settlement.settlement_reference,
                "tender_type": tender.tender_type,
                "amount_due": format_money(intent.amount_due),
                "amount_settled": format_money(intent.effective_settled),
                "settled_amount": format_money(settlement.amount),
                "change_due": format_money(tender.change_due or 0),
                "currency": settlement.currency,
            },
            "register_session_id": str(tender.register_session_id or ""),
            "operator_shift_id": str(tender.operator_shift_id or ""),
        }

    @classmethod
    @transaction.atomic
    def issue_receipt_for_settlement(cls, *, episode, settlement, actor, printer="", transport=PosPrintJob.Transport.SIMULATOR):
        episode = episode.__class__.all_objects.select_for_update().select_related(
            "tenant", "patient", "prescription", "branch"
        ).get(pk=episode.pk, tenant_id=episode.tenant_id)
        settlement = settlement.__class__.all_objects.select_related(
            "payment_tender__payment_intent", "payment_tender__register_session"
        ).get(pk=settlement.pk, tenant_id=episode.tenant_id)
        tender = settlement.payment_tender
        if tender.payment_intent.dispensing_episode_id != episode.id:
            raise ValidationError("Settlement does not belong to this dispensing episode.")
        if episode.payment_state != "PAID" or episode.status != "PAID":
            raise ValidationError("A receipt may be issued only after authoritative settlement completed.")
        if episode.payment_register_session_id and tender.register_session_id != episode.payment_register_session_id:
            raise ValidationError("Settlement register session does not match the settled episode.")

        existing = PosPrintDocument.all_objects.filter(
            settlement=settlement,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
        ).first()
        if existing:
            job = PosPrintJob.all_objects.filter(
                tenant=episode.tenant,
                document=existing,
                copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            ).first()
            return existing, job, True

        snapshot = cls._receipt_snapshot(episode=episode, settlement=settlement)
        document = PosPrintDocument.all_objects.create(
            tenant=episode.tenant,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
            document_number=snapshot["document_number"],
            snapshot=snapshot,
            document_hash=_hash_snapshot(snapshot),
            episode=episode,
            settlement=settlement,
            register_session=tender.register_session,
            created_by=actor,
        )
        job = PosPrintJob.all_objects.create(
            tenant=episode.tenant,
            document=document,
            branch=episode.branch,
            device_id=episode.payment_device_id,
            printer=printer,
            transport=transport,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
            copy_number=1,
            requested_by=actor,
            idempotency_key=f"receipt-original:{settlement.id}",
        )
        emit_event(
            tenant_id=str(episode.tenant_id),
            aggregate_type="PosPrintDocument",
            aggregate_id=str(document.id),
            event_type="POS_RECEIPT_QUEUED",
            payload={
                "episode_id": str(episode.id),
                "settlement_id": str(settlement.id),
                "document_number": document.document_number,
                "print_job_id": str(job.id),
            },
        )
        return document, job, False

    @staticmethod
    def receipt_status(*, settlement):
        document = PosPrintDocument.all_objects.filter(
            settlement=settlement,
            document_type=PosPrintDocument.DocumentType.PRESCRIPTION_RECEIPT,
        ).first()
        if not document:
            return None
        job = PosPrintJob.all_objects.filter(
            tenant=settlement.tenant,
            document=document,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
        ).first()
        return {
            "document_number": document.document_number,
            "document_id": str(document.id),
            "print_job_id": str(job.id) if job else "",
            "status": job.status if job else "QUEUED",
        }


class PosPrintJobService:
    @staticmethod
    def _require_print_capability(actor, job, capability):
        _require_capability(actor, job.tenant_id, capability)

    @classmethod
    @transaction.atomic
    def mark_rendered(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status in {PosPrintJob.Status.RENDERED, PosPrintJob.Status.PRINTED}:
            return job
        if job.status != PosPrintJob.Status.QUEUED:
            raise ValidationError(f"Print job is {job.status}; it cannot be rendered.")
        job.status = PosPrintJob.Status.RENDERED
        job.save(update_fields=["status", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def start_attempt(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status == PosPrintJob.Status.PRINTED:
            return job
        if job.status not in {
            PosPrintJob.Status.QUEUED,
            PosPrintJob.Status.RENDERED,
        }:
            raise ValidationError(f"Print job is {job.status}; it cannot be sent.")
        job.status = PosPrintJob.Status.SENDING
        job.attempt_count += 1
        job.last_attempt_at = timezone.now()
        job.failure_code = ""
        job.failure_message = ""
        job.save(update_fields=["status", "attempt_count", "last_attempt_at", "failure_code", "failure_message", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def record_result(cls, *, job, actor, succeeded, failure_code="", failure_message="", retryable=True):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().select_related("document").get(
            pk=job.pk, tenant_id=job.tenant_id
        )
        if job.status == PosPrintJob.Status.PRINTED:
            return job
        if job.status != PosPrintJob.Status.SENDING:
            raise ValidationError("A print result may be recorded only for a sending job.")
        if succeeded:
            job.status = PosPrintJob.Status.PRINTED
            job.printed_at = timezone.now()
            job.printed_by = actor
            job.failure_code = ""
            job.failure_message = ""
            event_type = "POS_PRINT_JOB_PRINTED"
        else:
            job.status = PosPrintJob.Status.RETRY_REQUIRED if retryable else PosPrintJob.Status.FAILED
            job.failure_code = str(failure_code or "TRANSPORT_FAILURE")[:64]
            job.failure_message = str(failure_message or "Printer transport did not confirm the document.")
            event_type = "POS_PRINT_JOB_FAILED"
        job.save()
        emit_event(
            tenant_id=str(job.tenant_id),
            aggregate_type="PosPrintJob",
            aggregate_id=str(job.id),
            event_type=event_type,
            payload={
                "document_id": str(job.document_id),
                "document_number": job.document.document_number,
                "status": job.status,
                "attempt_count": job.attempt_count,
                "failure_code": job.failure_code,
            },
        )
        return job

    @classmethod
    @transaction.atomic
    def retry(cls, *, job, actor):
        cls._require_print_capability(actor, job, "pos.document.print")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status != PosPrintJob.Status.RETRY_REQUIRED:
            raise ValidationError("Only a retry-required print job can be retried.")
        job.status = PosPrintJob.Status.QUEUED
        job.save(update_fields=["status", "updated_at"])
        return job

    @classmethod
    @transaction.atomic
    def cancel(cls, *, job, actor, reason):
        cls._require_print_capability(actor, job, "pos.document.cancel")
        if not reason or not reason.strip():
            raise ValidationError("Cancelling a print job requires a stated reason.")
        job = PosPrintJob.all_objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if job.status == PosPrintJob.Status.CANCELLED:
            return job
        if job.status not in {PosPrintJob.Status.QUEUED, PosPrintJob.Status.RENDERED}:
            raise ValidationError(f"Print job is {job.status}; it cannot be cancelled.")
        job.status = PosPrintJob.Status.CANCELLED
        job.cancelled_at = timezone.now()
        job.cancelled_by = actor
        job.cancellation_reason = reason.strip()
        job.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
                "updated_at",
            ]
        )
        return job

    @classmethod
    @transaction.atomic
    def request_reprint(cls, *, document, actor, reason, printer="", transport=PosPrintJob.Transport.SIMULATOR):
        _require_capability(actor, document.tenant_id, "pos.document.reprint")
        if not reason or not reason.strip():
            raise ValidationError("A reprint requires a stated reason.")
        document = PosPrintDocument.all_objects.select_for_update().get(
            pk=document.pk, tenant_id=document.tenant_id
        )
        original = PosPrintJob.all_objects.filter(
            tenant=document.tenant,
            document=document,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
        ).first()
        if not original or original.status != PosPrintJob.Status.PRINTED:
            raise ValidationError("A document can be reprinted only after its original print is confirmed.")
        copy_number = (
            PosPrintJob.all_objects.filter(tenant=document.tenant, document=document)
            .order_by("-copy_number")
            .values_list("copy_number", flat=True)
            .first()
            or 0
        ) + 1
        job = PosPrintJob.all_objects.create(
            tenant=document.tenant,
            document=document,
            branch=original.branch or getattr(document.episode, "branch", None),
            device_id=original.device_id,
            printer=printer or original.printer,
            transport=transport,
            copy_classification=PosPrintJob.CopyClassification.REPRINT,
            copy_number=copy_number,
            reprint_reason=reason.strip(),
            requested_by=actor,
            idempotency_key=f"reprint:{document.id}:{copy_number}",
        )
        return job
