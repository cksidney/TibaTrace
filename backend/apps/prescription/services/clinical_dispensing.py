from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.service import log_audit
from apps.cds.models import ClinicalEvaluation, ClinicalFinding, ClinicalOverride
from apps.cds.services import ClinicalDecisionSupportService
from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage
from apps.inventory.models import (
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryReservation,
)
from apps.inventory.services import (
    InventoryLedgerService,
    InventoryReservationService,
)
from apps.notifications.models import NotificationOutbox
from apps.practitioners.services import PrescriberGovernanceService
from apps.prescription.models import (
    ClinicalSubstitution,
    ClinicalWorkItem,
    DispensingAllocation,
    DispensingCheck,
    DispensingEpisode,
    DispensingLabel,
    DispensingLine,
    DispensingReservation,
    DispensingReversal,
    MedicineSupply,
    MedicineSupplyLine,
    PatientCounselling,
    PatientMedicationHistory,
    PatientReturn,
    PatientReturnLine,
    PharmacistClinicalReview,
    PharmacistIntervention,
    PharmacistVerification,
    Prescription,
    PrescriptionItem,
    PrescriptionValidationFinding,
)
from apps.prescription.services.workflow import PrescriptionWorkflowService
from apps.workflows.service import emit_event

CAPABILITY_ALIASES = {
    "prescriptions.intake": ("prescriptions.write",),
    "prescriptions.legal_validate": ("prescriptions.review",),
    "prescriptions.clinical_review": ("prescriptions.review",),
    "prescriptions.intervention.create": ("prescriptions.review",),
    "prescriptions.pharmacist_verify": ("prescriptions.approve",),
    "prescriptions.critical_override": ("cds.override",),
    "prescriptions.controlled_verify": ("prescriptions.approve",),
    "prescriptions.substitution.approve": ("dispensing.substitute",),
    "dispensing.reserve": ("dispensing.prepare",),
    "dispensing.allocate": ("dispensing.prepare",),
    "dispensing.check": ("dispensing.complete",),
    "dispensing.supply": ("dispensing.complete",),
    "dispensing.counsel": ("dispensing.complete",),
    "dispensing.return.receive": ("dispensing.reverse",),
    "dispensing.return.quality": ("dispensing.reverse",),
    "pos.shift.manage": ("dispensing.complete",),
}


def _has_capability(actor, tenant_id, capability):
    capabilities = (capability, *CAPABILITY_ALIASES.get(capability, ()))
    return bool(
        actor
        and any(
            actor.has_capability(candidate, tenant_id=tenant_id)
            for candidate in capabilities
        )
    )


def _require_capability(actor, tenant_id, capability):
    if not _has_capability(actor, tenant_id, capability):
        raise PermissionDenied(f"Capability {capability} is required.")


def _event_payload(
    *,
    tenant_id,
    actor=None,
    patient=None,
    prescription=None,
    prescription_item=None,
    episode=None,
    medicine=None,
    sku=None,
    batch=None,
    quantity=None,
    unit="",
    clinical_rule="",
    reason="",
    **extra,
):
    payload = {
        "tenant": str(tenant_id),
        "actor": str(getattr(actor, "id", "") or ""),
        "patient": str(getattr(patient, "id", "") or ""),
        "prescription": str(getattr(prescription, "id", "") or ""),
        "prescription_item": str(getattr(prescription_item, "id", "") or ""),
        "dispensing_episode": str(getattr(episode, "id", "") or ""),
        "medicine": str(getattr(medicine, "id", "") or ""),
        "sku": str(getattr(sku, "id", "") or ""),
        "batch": str(getattr(batch, "id", "") or ""),
        "quantity": str(quantity) if quantity is not None else "",
        "unit": unit,
        "clinical_rule": str(clinical_rule or ""),
        "reason": str(reason or ""),
        "correlation_id": str(extra.pop("correlation_id", "") or ""),
        "event_version": 1,
        "timestamp": timezone.now().isoformat(),
    }
    payload.update(extra)
    return payload


def _emit(event_type, aggregate, *, actor=None, **payload):
    return emit_event(
        tenant_id=aggregate.tenant_id,
        aggregate_type=aggregate.__class__.__name__,
        aggregate_id=aggregate.id,
        event_type=event_type,
        payload=_event_payload(
            tenant_id=aggregate.tenant_id,
            actor=actor,
            **payload,
        ),
    )


def _open_work_item(
    *,
    prescription,
    queue_type,
    required_capability,
    episode=None,
    due_at=None,
):
    existing = ClinicalWorkItem.all_objects.filter(
        tenant_id=prescription.tenant_id,
        queue_type=queue_type,
        prescription=prescription,
        dispensing_episode=episode,
        status__in=["OPEN", "IN_PROGRESS"],
    ).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            return ClinicalWorkItem.all_objects.create(
                tenant_id=prescription.tenant_id,
                queue_type=queue_type,
                prescription=prescription,
                dispensing_episode=episode,
                branch=episode.branch if episode else prescription.location,
                required_capability=required_capability,
                due_at=due_at,
            )
    except IntegrityError:
        return ClinicalWorkItem.all_objects.get(
            tenant_id=prescription.tenant_id,
            queue_type=queue_type,
            prescription=prescription,
            dispensing_episode=episode,
            status__in=["OPEN", "IN_PROGRESS"],
        )


def _close_work_items(*, prescription, queue_types, episode=None):
    ClinicalWorkItem.all_objects.filter(
        tenant_id=prescription.tenant_id,
        prescription=prescription,
        dispensing_episode=episode,
        queue_type__in=queue_types,
        status__in=["OPEN", "IN_PROGRESS"],
    ).update(status="CLOSED", closed_at=timezone.now())


def _notify(*, prescription, template_code, idempotency_key, payload):
    patient = prescription.patient
    recipient = patient.email or patient.phone
    if not recipient:
        return None
    notification, _ = NotificationOutbox.all_objects.get_or_create(
        tenant_id=prescription.tenant_id,
        idempotency_key=idempotency_key,
        defaults={
            "channel": "EMAIL" if patient.email else "SMS",
            "recipient": recipient,
            "template_code": template_code,
            "payload": payload,
        },
    )
    return notification


def _store_clinical_document(
    *,
    prescription,
    actor,
    document_type,
    document_number,
    source_id,
    content,
    revision=1,
    episode=None,
):
    generated_at = timezone.now()
    barcode_payload = f"DWT:DOC:{document_type}:{source_id}:R{revision}"
    payload = {
        "tenant_branding": {
            "tenant_id": str(prescription.tenant_id),
            "organization": prescription.organization.name,
        },
        "document_type": document_type,
        "document_number": document_number,
        "revision": revision,
        "patient_identity": {
            "patient_number": prescription.patient.patient_number,
            "display_name": prescription.patient.full_name,
            "privacy_policy": "CLINICAL_CONFIDENTIAL",
        },
        "prescription_reference": prescription.prescription_number,
        "pharmacist": actor.get_full_name() or actor.username,
        "generation_timestamp": generated_at.isoformat(),
        "barcode_payload": barcode_payload,
        **content,
    }
    encoded = json.dumps(payload, sort_keys=True, indent=2, default=str).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    safe_document_number = "".join(
        character
        if character.isalnum() or character in {"-", "_", "."}
        else "-"
        for character in str(document_number)
    )[:220]
    original_name = f"{safe_document_number}.txt"
    existing = StoredClinicalDocument.all_objects.filter(
        tenant_id=prescription.tenant_id,
        patient=prescription.patient,
        original_name=original_name,
        hash_sha256=digest,
    ).first()
    if existing:
        return existing
    document = LocalClinicalObjectStorage.store(
        tenant_id=prescription.tenant_id,
        patient=prescription.patient,
        original_name=original_name,
        content_type="text/plain",
        content=encoded,
        actor=actor,
    )
    document.metadata = {
        "document_type": document_type,
        "document_number": document_number,
        "revision": revision,
        "source_id": str(source_id),
        "prescription_id": str(prescription.id),
        "dispensing_episode_id": str(getattr(episode, "id", "") or ""),
        "document_hash": digest,
        "barcode_payload": barcode_payload,
        "privacy_classification": "CLINICAL_CONFIDENTIAL",
    }
    document.save()
    return document


def _active_verification(prescription, *, lock=False):
    queryset = PharmacistVerification.all_objects.filter(
        tenant_id=prescription.tenant_id,
        prescription=prescription,
        revoked_at__isnull=True,
    )
    if lock:
        queryset = queryset.select_for_update()
    verification = queryset.order_by("-verified_at").first()
    current_hash = PrescriptionWorkflowService.context_hash(prescription)
    if not verification or verification.context_hash != current_hash:
        raise ValidationError("A current pharmacist verification is required.")
    return verification


def _snapshot_item(item_data):
    data = dict(item_data)
    sku = data.get("prescribed_sku")
    if not sku:
        return data
    manufactured_product = sku.manufactured_product
    clinical_product = manufactured_product.clinical_product
    data.setdefault("prescribed_brand", manufactured_product)
    data.setdefault("prescribed_medicinal_product", clinical_product)
    data.setdefault("prescribed_description_snapshot", sku.display_name)
    data.setdefault("dosage_form_snapshot", clinical_product.dose_form.name)
    compositions = list(clinical_product.ingredients.select_related("active_substance"))
    data.setdefault(
        "active_ingredient_snapshot",
        [
            {
                "code": composition.active_substance.code,
                "name": composition.active_substance.canonical_name,
                "strength": str(composition.numerator_value),
                "unit": composition.numerator_unit,
            }
            for composition in compositions
        ],
    )
    data.setdefault(
        "strength_snapshot",
        ", ".join(
            f"{composition.numerator_value:g} {composition.numerator_unit}"
            for composition in compositions
        ),
    )
    return data


class PrescriptionIntakeService:
    @staticmethod
    @transaction.atomic
    def receive(*, tenant, actor, items, **data):
        _require_capability(actor, tenant.id, "prescriptions.intake")
        external_reference = str(
            data.get("external_prescription_reference") or ""
        ).strip()
        if external_reference:
            existing = Prescription.all_objects.filter(
                tenant=tenant,
                external_prescription_reference=external_reference,
            ).first()
            if existing:
                return existing
        patient = data["patient"]
        practitioner = data["practitioner"]
        organization = data["organization"]
        location = data["location"]
        for field_name, related in (
            ("patient", patient),
            ("practitioner", practitioner),
            ("organization", organization),
            ("location", location),
        ):
            if str(related.tenant_id) != str(tenant.id):
                raise ValidationError(
                    {field_name: "Related record is outside the active tenant."}
                )
        if not items:
            raise ValidationError({"items": "At least one prescription item is required."})
        data.setdefault("repeats_remaining", data.get("repeats_allowed", 0))
        prescription = Prescription.all_objects.create(
            tenant=tenant,
            status="RECEIVED",
            legal_validation_state="PENDING",
            clinical_review_state="NOT_STARTED",
            pharmacist_verification_state="NOT_VERIFIED",
            dispensing_state="NOT_STARTED",
            received_at=data.pop("received_at", None) or timezone.now(),
            created_by=actor,
            **data,
        )
        _open_work_item(
            prescription=prescription,
            queue_type="PRESCRIPTION_INTAKE",
            required_capability="prescriptions.intake",
        )
        for item_data in items:
            item_values = _snapshot_item(item_data)
            item_values.setdefault(
                "repeats_remaining",
                item_values.get("refills_authorized", 0),
            )
            PrescriptionItem.all_objects.create(
                tenant=tenant,
                prescription=prescription,
                **item_values,
            )
        _close_work_items(
            prescription=prescription,
            queue_types=["PRESCRIPTION_INTAKE"],
        )
        _open_work_item(
            prescription=prescription,
            queue_type="LEGAL_VALIDATION",
            required_capability="prescriptions.legal_validate",
        )
        log_audit(
            tenant_id=tenant.id,
            action="PRESCRIPTION_RECEIVED",
            model_name="Prescription",
            object_id=prescription.id,
            actor_id=actor.id,
            metadata={"prescription_number": prescription.prescription_number},
        )
        _emit(
            "PrescriptionReceived",
            prescription,
            actor=actor,
            patient=patient,
            prescription=prescription,
        )
        _store_clinical_document(
            prescription=prescription,
            actor=actor,
            document_type="PRESCRIPTION_INTAKE_RECORD",
            document_number=f"INTAKE-{prescription.prescription_number}",
            source_id=prescription.id,
            content={
                "source_channel": prescription.source_channel,
                "received_at": prescription.received_at,
                "prescriber": prescription.practitioner.professional_name,
                "items": [
                    {
                        "medicine": item.prescribed_description_snapshot
                        or item.medication_name,
                        "quantity": item.quantity,
                        "unit": item.unit,
                        "instructions": item.dosage_instruction,
                    }
                    for item in prescription.items.all()
                ],
            },
        )
        return prescription


class PrescriptionValidationService:
    @staticmethod
    def _finding(code, severity, message, category="LEGAL", item=None):
        return {
            "finding_code": code,
            "severity": severity,
            "message": message,
            "category": category,
            "prescription_item": item,
        }

    @classmethod
    @transaction.atomic
    def validate(cls, *, prescription, actor):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.legal_validate",
        )
        prescription = Prescription.all_objects.select_for_update().select_related(
            "patient",
            "practitioner",
        ).get(id=prescription.id, tenant_id=prescription.tenant_id)
        findings = []
        patient = prescription.patient
        if not patient.is_active or patient.is_deceased:
            findings.append(
                cls._finding(
                    "PATIENT_NOT_ELIGIBLE",
                    "CRITICAL",
                    "Patient is inactive or recorded as deceased.",
                    "PATIENT_IDENTITY",
                )
            )
        if not patient.patient_number:
            findings.append(
                cls._finding(
                    "PATIENT_IDENTITY_INCOMPLETE",
                    "HIGH",
                    "Patient number is missing.",
                    "PATIENT_IDENTITY",
                )
            )
        effective_date = (
            prescription.prescription_date
            or (
                timezone.localtime(prescription.issued_at).date()
                if prescription.issued_at
                else None
            )
        )
        if not effective_date:
            findings.append(
                cls._finding(
                    "PRESCRIPTION_DATE_MISSING",
                    "CRITICAL",
                    "Prescription date is required.",
                )
            )
        authority_findings = PrescriberGovernanceService.authority_findings(
            practitioner=prescription.practitioner,
            prescription_date=effective_date,
            controlled=prescription.is_controlled_medicine,
            required_scope=str(
                (prescription.metadata or {}).get("required_prescribing_scope", "")
            ),
        )
        findings.extend(
            cls._finding(code, severity, message, "PRESCRIBER")
            for code, severity, message in authority_findings
        )
        if prescription.expires_at and prescription.expires_at <= timezone.now():
            findings.append(
                cls._finding(
                    "PRESCRIPTION_EXPIRED",
                    "CRITICAL",
                    "Prescription has expired.",
                )
            )
        signature_required = bool(
            prescription.is_controlled_medicine
            or prescription.source_channel == "PAPER"
            or (prescription.metadata or {}).get("signature_required")
        )
        if signature_required and not (
            (prescription.metadata or {}).get("signature_evidence")
            or prescription.original_document_id
        ):
            findings.append(
                cls._finding(
                    "SIGNATURE_EVIDENCE_MISSING",
                    "CRITICAL",
                    "Required signature or original prescription evidence is missing.",
                )
            )
        items = list(
            PrescriptionItem.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
            )
        )
        if not items:
            findings.append(
                cls._finding(
                    "PRESCRIPTION_ITEMS_MISSING",
                    "CRITICAL",
                    "Prescription has no medicine instructions.",
                )
            )
        for item in items:
            if not (
                item.canonical_medicine_id
                or item.prescribed_medicinal_product_id
                or item.prescribed_sku_id
            ):
                findings.append(
                    cls._finding(
                        "MEDICINE_IDENTITY_AMBIGUOUS",
                        "CRITICAL",
                        "Medicine identity is incomplete or ambiguous.",
                        "MEDICINE_IDENTITY",
                        item,
                    )
                )
            if not item.strength_snapshot:
                findings.append(
                    cls._finding(
                        "STRENGTH_MISSING",
                        "HIGH",
                        "Prescribed strength is missing.",
                        "INSTRUCTION",
                        item,
                    )
                )
            if not item.dosage_form_snapshot:
                findings.append(
                    cls._finding(
                        "DOSAGE_FORM_MISSING",
                        "HIGH",
                        "Dosage form is missing.",
                        "INSTRUCTION",
                        item,
                    )
                )
            if not item.route:
                findings.append(
                    cls._finding(
                        "ROUTE_MISSING",
                        "HIGH",
                        "Administration route is missing.",
                        "INSTRUCTION",
                        item,
                    )
                )
            if not item.dosage_instruction.strip():
                findings.append(
                    cls._finding(
                        "DOSAGE_INSTRUCTION_MISSING",
                        "CRITICAL",
                        "Dosage instruction is required.",
                        "INSTRUCTION",
                        item,
                    )
                )
            if item.quantity <= 0:
                findings.append(
                    cls._finding(
                        "QUANTITY_INVALID",
                        "CRITICAL",
                        "Prescribed quantity must be positive.",
                        "INSTRUCTION",
                        item,
                    )
                )
            if item.is_controlled and not prescription.is_controlled_medicine:
                findings.append(
                    cls._finding(
                        "CONTROLLED_FLAG_INCONSISTENT",
                        "CRITICAL",
                        "Controlled medicine item requires a controlled prescription.",
                        "CONTROLLED_MEDICINE",
                        item,
                    )
                )
        current_codes = set()
        for finding in findings:
            item = finding.pop("prescription_item")
            current_codes.add((finding["finding_code"], item.id if item else None))
            PrescriptionValidationFinding.all_objects.update_or_create(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
                prescription_item=item,
                finding_code=finding["finding_code"],
                defaults={**finding, "status": "OPEN"},
            )
        for old_finding in PrescriptionValidationFinding.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            status__in=["OPEN", "ACKNOWLEDGED"],
        ):
            key = (
                old_finding.finding_code,
                old_finding.prescription_item_id,
            )
            if key not in current_codes:
                old_finding.status = "RESOLVED"
                old_finding.resolved_by = actor
                old_finding.resolution_reason = "Resolved by repeat validation."
                old_finding.resolved_at = timezone.now()
                old_finding.save()
        blocking = any(
            finding["severity"] in {"HIGH", "CRITICAL"} for finding in findings
        )
        prescription.legal_validation_state = "FAILED" if blocking else "PASSED"
        prescription.status = "INTAKE_REVIEW" if blocking else "LEGALLY_VALIDATED"
        prescription.reviewed_by = actor
        prescription.save()
        event_type = (
            "PrescriptionValidationFailed"
            if blocking
            else "PrescriptionLegallyValidated"
        )
        _emit(
            event_type,
            prescription,
            actor=actor,
            patient=patient,
            prescription=prescription,
            reason="; ".join(finding["finding_code"] for finding in findings),
            finding_count=len(findings),
        )
        if blocking:
            _open_work_item(
                prescription=prescription,
                queue_type="LEGAL_VALIDATION",
                required_capability="prescriptions.legal_validate",
            )
            _notify(
                prescription=prescription,
                template_code="PRESCRIPTION_REJECTED",
                idempotency_key=f"prescription-rejected:{prescription.id}:legal",
                payload={
                    "prescription_reference": prescription.prescription_number,
                    "action": "CONTACT_PHARMACY",
                },
            )
        else:
            _close_work_items(
                prescription=prescription,
                queue_types=["LEGAL_VALIDATION", "PRESCRIPTION_INTAKE"],
            )
            _open_work_item(
                prescription=prescription,
                queue_type="CLINICAL_REVIEW",
                required_capability="prescriptions.clinical_review",
            )
            if prescription.is_controlled_medicine:
                _open_work_item(
                    prescription=prescription,
                    queue_type="CONTROLLED_MEDICINE_REVIEW",
                    required_capability="prescriptions.controlled_verify",
                )
                _notify(
                    prescription=prescription,
                    template_code="CONTROLLED_MEDICINE_APPROVAL_REQUIRED",
                    idempotency_key=f"controlled-review:{prescription.id}",
                    payload={
                        "prescription_reference": prescription.prescription_number,
                        "action": "CLINICAL_REVIEW_PENDING",
                    },
                )
            if (
                prescription.expires_at
                and prescription.expires_at <= timezone.now() + timedelta(days=7)
            ):
                _notify(
                    prescription=prescription,
                    template_code="PRESCRIPTION_EXPIRING",
                    idempotency_key=f"prescription-expiring:{prescription.id}",
                    payload={
                        "prescription_reference": prescription.prescription_number,
                        "expiry_date": prescription.expires_at.date().isoformat(),
                    },
                )
        return prescription


class PrescriptionLifecycleService:
    @staticmethod
    @transaction.atomic
    def hold(*, prescription, actor, reason):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.clinical_review",
        )
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A hold reason is required."})
        prescription = Prescription.all_objects.select_for_update().get(
            id=prescription.id,
            tenant_id=prescription.tenant_id,
        )
        if prescription.status in {"CANCELLED", "CLOSED", "EXPIRED"}:
            raise ValidationError("Closed prescriptions cannot be placed on hold.")
        prescription.metadata = {
            **(prescription.metadata or {}),
            "pre_hold_status": prescription.status,
            "hold_reason": reason,
            "held_at": timezone.now().isoformat(),
            "held_by": str(actor.id),
        }
        prescription.status = "ON_HOLD"
        prescription.save()
        _open_work_item(
            prescription=prescription,
            queue_type="PRESCRIBER_CLARIFICATION",
            required_capability="prescriptions.clinical_review",
        )
        _notify(
            prescription=prescription,
            template_code="CLARIFICATION_REQUIRED",
            idempotency_key=f"clarification-required:{prescription.id}:{prescription.updated_at}",
            payload={
                "prescription_reference": prescription.prescription_number,
                "action": "CONTACT_PHARMACY",
            },
        )
        return prescription

    @staticmethod
    @transaction.atomic
    def release_hold(*, prescription, actor, reason):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.clinical_review",
        )
        prescription = Prescription.all_objects.select_for_update().get(
            id=prescription.id,
            tenant_id=prescription.tenant_id,
        )
        if prescription.status != "ON_HOLD":
            raise ValidationError("Prescription is not on hold.")
        active_verification = PharmacistVerification.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            revoked_at__isnull=True,
            context_hash=PrescriptionWorkflowService.context_hash(prescription),
        ).exists()
        prescription.status = (
            "PHARMACIST_VERIFIED"
            if active_verification
            else "LEGALLY_VALIDATED"
            if prescription.legal_validation_state == "PASSED"
            else "INTAKE_REVIEW"
        )
        prescription.metadata = {
            **(prescription.metadata or {}),
            "hold_release_reason": str(reason or ""),
            "hold_released_at": timezone.now().isoformat(),
            "hold_released_by": str(actor.id),
        }
        prescription.save()
        _close_work_items(
            prescription=prescription,
            queue_types=["PRESCRIBER_CLARIFICATION", "PATIENT_CLARIFICATION"],
        )
        return prescription

    @staticmethod
    @transaction.atomic
    def cancel(*, prescription, actor, reason):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.intake",
        )
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A cancellation reason is required."})
        prescription = Prescription.all_objects.select_for_update().get(
            id=prescription.id,
            tenant_id=prescription.tenant_id,
        )
        if prescription.status in {"SUPPLIED", "CLOSED"}:
            raise ValidationError("Supplied prescriptions cannot be cancelled.")
        active_verifications = PharmacistVerification.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            revoked_at__isnull=True,
        )
        verification_ids = list(active_verifications.values_list("id", flat=True))
        active_verifications.update(
            revoked_at=timezone.now(),
            revoked_reason=f"Prescription cancelled: {reason}",
        )
        for reservation in InventoryReservation.all_objects.filter(
            tenant_id=prescription.tenant_id,
            dispensing_reservation__episode__prescription=prescription,
            status__in=["PENDING", "ALLOCATED"],
        ):
            InventoryReservationService.release_reservation(
                reservation=reservation,
                actor=actor,
            )
        prescription.status = "CANCELLED"
        prescription.pharmacist_verification_state = (
            "REVOKED" if verification_ids else "NOT_VERIFIED"
        )
        prescription.dispensing_state = "NOT_STARTED"
        prescription.metadata = {
            **(prescription.metadata or {}),
            "cancellation_reason": reason,
            "cancelled_by": str(actor.id),
            "cancelled_at": timezone.now().isoformat(),
        }
        prescription.save()
        ClinicalWorkItem.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            status__in=["OPEN", "IN_PROGRESS"],
        ).update(status="CANCELLED", closed_at=timezone.now())
        return prescription


class PharmacistReviewService:
    @staticmethod
    @transaction.atomic
    def start(*, prescription, actor, run_cds=True):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.clinical_review",
        )
        prescription = Prescription.all_objects.select_for_update().get(
            id=prescription.id,
            tenant_id=prescription.tenant_id,
        )
        if prescription.legal_validation_state != "PASSED":
            raise ValidationError(
                "Legal validation must pass before pharmacist clinical review."
            )
        context_hash = PrescriptionWorkflowService.context_hash(prescription)
        current = PharmacistClinicalReview.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            review_completed_at__isnull=True,
        ).first()
        if current and current.context_hash == context_hash:
            return current
        version = (
            PharmacistClinicalReview.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
            ).count()
            + 1
        )
        review = PharmacistClinicalReview.all_objects.create(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            reviewing_pharmacist=actor,
            context_hash=context_hash,
            version=version,
        )
        prescription.clinical_review_state = "IN_PROGRESS"
        prescription.status = "CLINICAL_REVIEW"
        prescription.reviewed_by = actor
        prescription.save()
        if run_cds:
            evaluation = ClinicalDecisionSupportService.evaluate(
                prescription=prescription,
                actor=actor,
            )
            evaluation_findings = list(
                ClinicalFinding.all_objects.filter(evaluation=evaluation)
            )
            for finding in evaluation_findings:
                _emit(
                    "ClinicalFindingRaised",
                    prescription,
                    actor=actor,
                    patient=prescription.patient,
                    prescription=prescription,
                    prescription_item=finding.prescription_item,
                    medicine=finding.affected_medicine,
                    clinical_rule=f"{finding.rule_id}:{finding.rule_version}",
                    reason=finding.explanation,
                    severity=finding.severity,
                    finding=str(finding.id),
                )
            if any(
                finding.severity in {"BLOCK", "CRITICAL"}
                and finding.resolution_status
                in {"OPEN", "ACKNOWLEDGED", "INTERVENTION_REQUIRED"}
                for finding in evaluation_findings
            ):
                _open_work_item(
                    prescription=prescription,
                    queue_type="CRITICAL_DUR_FINDING",
                    required_capability="prescriptions.critical_override",
                )
        _emit(
            "ClinicalReviewStarted",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            review=str(review.id),
        )
        return review

    @staticmethod
    @transaction.atomic
    def resolve_finding(
        *,
        finding,
        actor,
        resolution_status,
        reason,
        clinical_justification="",
        supporting_evidence=None,
    ):
        _require_capability(
            actor,
            finding.tenant_id,
            "prescriptions.clinical_review",
        )
        finding = ClinicalFinding.all_objects.select_for_update().get(
            id=finding.id,
            tenant_id=finding.tenant_id,
        )
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A clinical resolution reason is required."})
        resolution_status = str(resolution_status or "").upper()
        if resolution_status == "OVERRIDDEN":
            _require_capability(
                actor,
                finding.tenant_id,
                "prescriptions.critical_override",
            )
            ClinicalOverride.all_objects.create(
                tenant_id=finding.tenant_id,
                finding=finding,
                prescription=finding.prescription,
                authorized_by=actor,
                reason=reason,
                clinical_justification=clinical_justification or reason,
                rule_version=finding.rule_version,
                supporting_evidence=supporting_evidence or {},
            )
        elif resolution_status not in {"RESOLVED", "NOT_APPLICABLE", "ACKNOWLEDGED"}:
            raise ValidationError({"resolution_status": "Unsupported resolution status."})
        finding.resolution_status = resolution_status
        finding.resolved_by = actor
        finding.resolution_reason = reason
        finding.resolved_at = timezone.now()
        finding.save()
        unresolved_critical = ClinicalFinding.all_objects.filter(
            tenant_id=finding.tenant_id,
            prescription=finding.prescription,
            severity__in=["BLOCK", "CRITICAL"],
            resolution_status__in=[
                "OPEN",
                "ACKNOWLEDGED",
                "INTERVENTION_REQUIRED",
            ],
        ).exists()
        if not unresolved_critical:
            _close_work_items(
                prescription=finding.prescription,
                queue_types=["CRITICAL_DUR_FINDING"],
            )
        _emit(
            "ClinicalFindingResolved",
            finding.prescription,
            actor=actor,
            patient=finding.patient,
            prescription=finding.prescription,
            prescription_item=finding.prescription_item,
            clinical_rule=f"{finding.rule_id}:{finding.rule_version}",
            reason=reason,
            resolution_status=resolution_status,
            finding=str(finding.id),
        )
        return finding

    @staticmethod
    @transaction.atomic
    def complete(*, review, actor, outcome, notes=""):
        _require_capability(
            actor,
            review.tenant_id,
            "prescriptions.clinical_review",
        )
        review = PharmacistClinicalReview.all_objects.select_for_update().get(
            id=review.id,
            tenant_id=review.tenant_id,
        )
        current_hash = PrescriptionWorkflowService.context_hash(review.prescription)
        if review.context_hash != current_hash:
            raise ValidationError("Prescription changed during clinical review.")
        unresolved_critical = ClinicalFinding.all_objects.filter(
            tenant_id=review.tenant_id,
            prescription=review.prescription,
            severity__in=["BLOCK", "CRITICAL"],
            resolution_status__in=[
                "OPEN",
                "ACKNOWLEDGED",
                "INTERVENTION_REQUIRED",
            ],
        ).exists()
        open_interventions = PharmacistIntervention.all_objects.filter(
            tenant_id=review.tenant_id,
            review=review,
            status__in=["OPEN", "AWAITING_RESPONSE"],
        ).exists()
        approved_outcomes = {"APPROVED", "APPROVED_WITH_COUNSELLING"}
        if outcome in approved_outcomes and (unresolved_critical or open_interventions):
            raise ValidationError(
                "Blocking findings and interventions must be resolved before approval."
            )
        review.outcome = outcome
        review.notes = notes
        review.review_completed_at = timezone.now()
        review.verification_decision = (
            "ELIGIBLE" if outcome in approved_outcomes else "NOT_ELIGIBLE"
        )
        review.save()
        prescription = review.prescription
        prescription.clinical_review_state = (
            "COMPLETED" if outcome in approved_outcomes else "BLOCKED"
        )
        prescription.status = (
            "LEGALLY_VALIDATED"
            if outcome in approved_outcomes
            else "INTERVENTION_REQUIRED"
        )
        prescription.save()
        if outcome in approved_outcomes:
            _close_work_items(
                prescription=prescription,
                queue_types=["CLINICAL_REVIEW", "CRITICAL_DUR_FINDING"],
            )
            _open_work_item(
                prescription=prescription,
                queue_type="PHARMACIST_VERIFICATION",
                required_capability="prescriptions.pharmacist_verify",
            )
        elif outcome == "PRESCRIBER_CONTACT_REQUIRED":
            _open_work_item(
                prescription=prescription,
                queue_type="PRESCRIBER_CLARIFICATION",
                required_capability="prescriptions.intervention.create",
            )
        elif outcome == "PATIENT_CONTACT_REQUIRED":
            _open_work_item(
                prescription=prescription,
                queue_type="PATIENT_CLARIFICATION",
                required_capability="prescriptions.intervention.create",
            )
        _store_clinical_document(
            prescription=prescription,
            actor=actor,
            document_type="CLINICAL_REVIEW_SUMMARY",
            document_number=(
                f"REVIEW-{prescription.prescription_number}-V{review.version}"
            ),
            source_id=review.id,
            revision=review.version,
            content={
                "review_started_at": review.review_started_at,
                "review_completed_at": review.review_completed_at,
                "outcome": review.outcome,
                "notes": review.notes,
                "clinical_findings": list(
                    ClinicalFinding.all_objects.filter(
                        tenant_id=review.tenant_id,
                        prescription=prescription,
                    ).values(
                        "rule_id",
                        "rule_version",
                        "severity",
                        "resolution_status",
                    )
                ),
            },
        )
        return review


class PharmacistInterventionService:
    @staticmethod
    @transaction.atomic
    def create(*, review, actor, intervention_type, intervention_request, **data):
        _require_capability(
            actor,
            review.tenant_id,
            "prescriptions.intervention.create",
        )
        intervention = PharmacistIntervention.all_objects.create(
            tenant_id=review.tenant_id,
            prescription=review.prescription,
            review=review,
            actor=actor,
            intervention_type=intervention_type,
            intervention_request=intervention_request,
            **data,
        )
        review.prescription.clinical_review_state = "FINDINGS_OPEN"
        review.prescription.status = "INTERVENTION_REQUIRED"
        review.prescription.save()
        clarification_queue = (
            "PATIENT_CLARIFICATION"
            if str(intervention.contacted_party).upper().startswith("PATIENT")
            else "PRESCRIBER_CLARIFICATION"
        )
        _open_work_item(
            prescription=review.prescription,
            queue_type=clarification_queue,
            required_capability="prescriptions.intervention.create",
        )
        _emit(
            "PharmacistInterventionCreated",
            review.prescription,
            actor=actor,
            patient=review.prescription.patient,
            prescription=review.prescription,
            prescription_item=intervention.prescription_item,
            reason=intervention_request,
            intervention=str(intervention.id),
        )
        intervention.supporting_document = _store_clinical_document(
            prescription=review.prescription,
            actor=actor,
            document_type="PHARMACIST_INTERVENTION_RECORD",
            document_number=(
                f"INTERVENTION-{review.prescription.prescription_number}-"
                f"{intervention.id}"
            ),
            source_id=intervention.id,
            content={
                "intervention_type": intervention.intervention_type,
                "contacted_party": intervention.contacted_party,
                "contact_method": intervention.contact_method,
                "request": intervention.intervention_request,
                "status": intervention.status,
            },
        )
        intervention.save()
        _notify(
            prescription=review.prescription,
            template_code="CLARIFICATION_REQUIRED",
            idempotency_key=f"intervention-clarification:{intervention.id}",
            payload={
                "prescription_reference": review.prescription.prescription_number,
                "action": "CONTACT_PHARMACY",
            },
        )
        return intervention

    @staticmethod
    @transaction.atomic
    def resolve(*, intervention, actor, response, outcome):
        _require_capability(
            actor,
            intervention.tenant_id,
            "prescriptions.intervention.create",
        )
        intervention = PharmacistIntervention.all_objects.select_for_update().get(
            id=intervention.id,
            tenant_id=intervention.tenant_id,
        )
        intervention.response = response
        intervention.outcome = outcome
        intervention.status = "RESOLVED"
        intervention.resolved_at = timezone.now()
        intervention.save()
        if not PharmacistIntervention.all_objects.filter(
            tenant_id=intervention.tenant_id,
            prescription=intervention.prescription,
            status__in=["OPEN", "AWAITING_RESPONSE"],
        ).exists():
            _close_work_items(
                prescription=intervention.prescription,
                queue_types=[
                    "PRESCRIBER_CLARIFICATION",
                    "PATIENT_CLARIFICATION",
                ],
            )
        _emit(
            "PrescriberClarificationReceived",
            intervention.prescription,
            actor=actor,
            patient=intervention.prescription.patient,
            prescription=intervention.prescription,
            prescription_item=intervention.prescription_item,
            reason=response,
            intervention=str(intervention.id),
        )
        intervention.supporting_document = _store_clinical_document(
            prescription=intervention.prescription,
            actor=actor,
            document_type="PHARMACIST_INTERVENTION_RECORD",
            document_number=(
                f"INTERVENTION-{intervention.prescription.prescription_number}-"
                f"{intervention.id}-RESOLVED"
            ),
            source_id=intervention.id,
            revision=2,
            content={
                "intervention_type": intervention.intervention_type,
                "contacted_party": intervention.contacted_party,
                "request": intervention.intervention_request,
                "response": intervention.response,
                "outcome": intervention.outcome,
                "status": intervention.status,
                "resolved_at": intervention.resolved_at,
            },
        )
        intervention.save()
        return intervention


class PharmacistVerificationService:
    @staticmethod
    @transaction.atomic
    def verify(
        *,
        prescription,
        actor,
        idempotency_key,
        decision="VERIFIED",
        clinical_justification="",
    ):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.pharmacist_verify",
        )
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})
        existing = PharmacistVerification.all_objects.filter(
            tenant_id=prescription.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        prescription = Prescription.all_objects.select_for_update().select_related(
            "patient",
            "practitioner",
        ).get(id=prescription.id, tenant_id=prescription.tenant_id)
        if prescription.legal_validation_state != "PASSED":
            raise ValidationError("Legal validation has not passed.")
        context_hash = PrescriptionWorkflowService.context_hash(prescription)
        review = (
            PharmacistClinicalReview.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
                review_completed_at__isnull=False,
                outcome__in=["APPROVED", "APPROVED_WITH_COUNSELLING"],
                context_hash=context_hash,
            )
            .order_by("-version")
            .first()
        )
        if not review:
            raise ValidationError("A current completed pharmacist review is required.")
        evaluation = (
            ClinicalEvaluation.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
                context_hash=context_hash,
            )
            .order_by("-created_at")
            .first()
        )
        if not evaluation or evaluation.status in {
            "KNOWLEDGE_UNAVAILABLE",
            "ERROR",
        }:
            raise ValidationError("A current non-blocking DUR evaluation is required.")
        unresolved_critical = ClinicalFinding.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            severity__in=["BLOCK", "CRITICAL"],
            resolution_status__in=[
                "OPEN",
                "ACKNOWLEDGED",
                "INTERVENTION_REQUIRED",
            ],
        ).exists()
        unresolved_validation = PrescriptionValidationFinding.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            severity__in=["HIGH", "CRITICAL"],
            status__in=["OPEN", "ACKNOWLEDGED"],
        ).exists()
        open_interventions = PharmacistIntervention.all_objects.filter(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            status__in=["OPEN", "AWAITING_RESPONSE"],
        ).exists()
        if unresolved_critical or unresolved_validation or open_interventions:
            raise ValidationError(
                "Unresolved blocking findings or interventions prevent verification."
            )
        authority_findings = [
            *PrescriberGovernanceService.authority_findings(
                practitioner=prescription.practitioner,
                prescription_date=prescription.prescription_date,
                controlled=prescription.is_controlled_medicine,
            ),
            *PrescriberGovernanceService.authority_findings(
                practitioner=prescription.practitioner,
                prescription_date=timezone.localdate(),
                controlled=prescription.is_controlled_medicine,
            ),
        ]
        if authority_findings:
            raise ValidationError(
                {code: message for code, _severity, message in authority_findings}
            )
        if prescription.expires_at and prescription.expires_at <= timezone.now():
            raise ValidationError("Expired prescriptions cannot be verified.")
        if not prescription.patient.is_active or prescription.patient.is_deceased:
            raise ValidationError("Patient is not eligible for medicine supply.")
        if prescription.is_controlled_medicine:
            _require_capability(
                actor,
                prescription.tenant_id,
                "prescriptions.controlled_verify",
            )
            if not prescription.patient.identifiers.filter(
                verification_status="VERIFIED"
            ).exists():
                raise ValidationError(
                    "Controlled prescriptions require verified patient identity."
                )
            if not (
                prescription.original_document_id
                or (prescription.metadata or {}).get("signature_evidence")
            ):
                raise ValidationError(
                    "Controlled prescriptions require original prescription evidence."
                )
        checks = {
            "legal_validation_passed": True,
            "clinical_review_completed": True,
            "blocking_findings_resolved": True,
            "interventions_completed": True,
            "medicine_identity_confirmed": True,
            "dose_and_instructions_confirmed": True,
            "controlled_requirements_satisfied": True,
            "patient_profile_reviewed": True,
            "prescription_valid": True,
            "pharmacist_authority_confirmed": True,
            "prescriber_authority_confirmed": True,
            "controlled_authority_confirmed": (
                not prescription.is_controlled_medicine
                or actor.has_capability(
                    "prescriptions.controlled_verify",
                    tenant_id=prescription.tenant_id,
                )
            ),
            "verified_actor_id": str(actor.id),
            "prescriber_id": str(prescription.practitioner_id),
            "prescriber_authority": {
                "status": prescription.practitioner.status,
                "verification_state": (
                    prescription.practitioner.verification_state
                ),
                "licence_status": prescription.practitioner.licence_status,
                "licence_issue_date": (
                    prescription.practitioner.licence_issue_date.isoformat()
                    if prescription.practitioner.licence_issue_date
                    else None
                ),
                "licence_expiry_date": (
                    prescription.practitioner.licence_expiry_date.isoformat()
                    if prescription.practitioner.licence_expiry_date
                    else None
                ),
                "controlled_medicine_authority": (
                    prescription.practitioner.controlled_medicine_authority
                ),
            },
        }
        verification = PharmacistVerification.all_objects.create(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            review=review,
            verified_by=actor,
            decision=decision,
            context_hash=context_hash,
            verification_checks=checks,
            clinical_justification=clinical_justification,
            idempotency_key=idempotency_key,
        )
        prescription.pharmacist_verification_state = "VERIFIED"
        prescription.clinical_review_state = "COMPLETED"
        prescription.dispensing_state = "READY"
        prescription.status = "PHARMACIST_VERIFIED"
        prescription.approved_by = actor
        prescription.approved_at = verification.verified_at
        prescription.clinical_context_hash = context_hash
        prescription.save()
        _close_work_items(
            prescription=prescription,
            queue_types=[
                "PHARMACIST_VERIFICATION",
                "CLINICAL_REVIEW",
                "CONTROLLED_MEDICINE_REVIEW",
            ],
        )
        _open_work_item(
            prescription=prescription,
            queue_type="READY_FOR_DISPENSING",
            required_capability="dispensing.reserve",
        )
        log_audit(
            tenant_id=prescription.tenant_id,
            action="PRESCRIPTION_PHARMACIST_VERIFIED",
            model_name="PharmacistVerification",
            object_id=verification.id,
            actor_id=actor.id,
            metadata={"prescription_id": str(prescription.id)},
        )
        _emit(
            "PrescriptionPharmacistVerified",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            reason=clinical_justification,
            verification=str(verification.id),
        )
        _notify(
            prescription=prescription,
            template_code="PRESCRIPTION_VERIFIED",
            idempotency_key=f"prescription-verified:{verification.id}",
            payload={"prescription_reference": prescription.prescription_number},
        )
        return verification

    @staticmethod
    @transaction.atomic
    def revoke(*, prescription, actor, reason):
        _require_capability(
            actor,
            prescription.tenant_id,
            "prescriptions.pharmacist_verify",
        )
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A revocation reason is required."})
        verification = _active_verification(prescription, lock=True)
        PharmacistVerification.all_objects.filter(
            tenant_id=prescription.tenant_id,
            id=verification.id,
        ).update(
            revoked_at=timezone.now(),
            revoked_reason=reason,
        )
        Prescription.all_objects.filter(
            tenant_id=prescription.tenant_id,
            id=prescription.id,
        ).update(
            pharmacist_verification_state="REVOKED",
            dispensing_state="NOT_STARTED",
            status="CLINICAL_REVIEW",
        )
        _open_work_item(
            prescription=prescription,
            queue_type="CLINICAL_REVIEW",
            required_capability="prescriptions.clinical_review",
        )
        if prescription.is_controlled_medicine:
            _open_work_item(
                prescription=prescription,
                queue_type="CONTROLLED_MEDICINE_REVIEW",
                required_capability="prescriptions.controlled_verify",
            )
        _emit(
            "PrescriptionVerificationRevoked",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            reason=reason,
            verification=str(verification.id),
        )
        return PharmacistVerification.all_objects.get(
            tenant_id=prescription.tenant_id,
            id=verification.id,
        )


class ClinicalSubstitutionService:
    @staticmethod
    @transaction.atomic
    def propose(
        *,
        prescription_item,
        proposed_sku,
        actor,
        equivalence_basis,
        reason,
        price_impact=0,
        stock_reason="",
        prescriber_approved=False,
        patient_consented=False,
        pharmacist_approved=False,
    ):
        _require_capability(
            actor,
            prescription_item.tenant_id,
            "prescriptions.substitution.approve",
        )
        if prescription_item.substitution_policy == "NO_SUBSTITUTION":
            raise ValidationError("Substitution is prohibited for this prescription item.")
        if proposed_sku.tenant_id != prescription_item.tenant_id:
            raise ValidationError("Proposed SKU is outside the prescription tenant.")
        requires_prescriber = (
            prescription_item.substitution_policy
            == "THERAPEUTIC_SUBSTITUTION_REQUIRES_PRESCRIBER"
        )
        requires_patient = (
            prescription_item.substitution_policy == "PATIENT_CONSENT_REQUIRED"
        )
        approved = (
            pharmacist_approved
            and (prescriber_approved or not requires_prescriber)
            and (patient_consented or not requires_patient)
        )
        substitution = ClinicalSubstitution.all_objects.create(
            tenant_id=prescription_item.tenant_id,
            prescription=prescription_item.prescription,
            prescription_item=prescription_item,
            prescribed_sku=prescription_item.prescribed_sku,
            proposed_sku=proposed_sku,
            equivalence_basis=equivalence_basis,
            price_impact=price_impact,
            stock_reason=stock_reason,
            prescriber_approved=prescriber_approved,
            patient_consented=patient_consented,
            pharmacist_approved=pharmacist_approved,
            approved_by=actor if approved else None,
            status="APPROVED" if approved else "PROPOSED",
            reason=reason,
        )
        _notify(
            prescription=prescription_item.prescription,
            template_code="SUBSTITUTION_PROPOSED",
            idempotency_key=f"substitution-proposed:{substitution.id}",
            payload={
                "prescription_reference": (
                    prescription_item.prescription.prescription_number
                ),
                "action": "CONTACT_PHARMACY",
            },
        )
        return substitution


class DispensingEpisodeService:
    @staticmethod
    @transaction.atomic
    def create(
        *,
        prescription,
        branch,
        pharmacy_location,
        actor,
        idempotency_key,
        supply_method="PATIENT_COLLECTION",
        sales_order=None,
        payment_gate_state=None,
        notes="",
    ):
        _require_capability(actor, prescription.tenant_id, "dispensing.reserve")
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})
        existing = DispensingEpisode.all_objects.filter(
            tenant_id=prescription.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        _active_verification(prescription)
        if branch.tenant_id != prescription.tenant_id:
            raise ValidationError("Branch is outside the prescription tenant.")
        if (
            pharmacy_location.tenant_id != prescription.tenant_id
            or pharmacy_location.branch_id != branch.id
        ):
            raise ValidationError("Pharmacy inventory location is outside the branch.")
        if prescription.is_controlled_medicine and not (
            pharmacy_location.controlled_drug_capability
        ):
            raise ValidationError(
                "Controlled medicines require a controlled-capable inventory location."
            )
        if sales_order and sales_order.tenant_id != prescription.tenant_id:
            raise ValidationError("Sales order is outside the prescription tenant.")
        episode = DispensingEpisode.all_objects.create(
            tenant_id=prescription.tenant_id,
            dispensing_number=f"DSP-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
            prescription=prescription,
            patient=prescription.patient,
            branch=branch,
            pharmacy_location=pharmacy_location,
            pharmacist=actor,
            supply_method=supply_method,
            sales_order=sales_order,
            payment_gate_state=payment_gate_state
            or ("PENDING" if sales_order else "NOT_REQUIRED"),
            notes=notes,
            idempotency_key=idempotency_key,
        )
        _close_work_items(
            prescription=prescription,
            queue_types=["READY_FOR_DISPENSING"],
        )
        _open_work_item(
            prescription=prescription,
            episode=episode,
            queue_type="DISPENSING_PREPARATION",
            required_capability="dispensing.prepare",
        )
        return episode


class DispensingReservationService:
    @staticmethod
    def _authorized_remaining(item):
        return max(
            Decimal("0"),
            item.total_authorized_quantity - item.quantity_supplied_total,
        )

    @classmethod
    @transaction.atomic
    def reserve(
        cls,
        *,
        episode,
        prescription_item,
        quantity,
        actor,
        idempotency_key,
        minimum_shelf_life_days=0,
        substitute_sku=None,
    ):
        _require_capability(actor, episode.tenant_id, "dispensing.reserve")
        idempotency_key = str(idempotency_key or "").strip()
        existing = DispensingReservation.all_objects.filter(
            tenant_id=episode.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        episode = DispensingEpisode.all_objects.select_for_update().get(
            id=episode.id,
            tenant_id=episode.tenant_id,
        )
        prescription = episode.prescription
        _active_verification(prescription, lock=True)
        item = PrescriptionItem.all_objects.select_for_update().get(
            id=prescription_item.id,
            tenant_id=episode.tenant_id,
            prescription=prescription,
        )
        quantity = Decimal(str(quantity))
        if quantity <= 0:
            raise ValidationError({"quantity": "Reservation quantity must be positive."})
        if quantity > cls._authorized_remaining(item):
            raise ValidationError("Reservation exceeds the remaining authorized quantity.")
        if item.quantity_supplied_total >= item.quantity:
            RepeatDispensingService.validate(
                prescription_item=item,
                actor=actor,
            )
        sku = item.prescribed_sku
        substitution = None
        if substitute_sku:
            substitution = ClinicalSubstitution.all_objects.filter(
                tenant_id=episode.tenant_id,
                prescription_item=item,
                proposed_sku=substitute_sku,
                status="APPROVED",
            ).first()
            if not substitution:
                raise ValidationError("Clinical substitution has not been approved.")
            sku = substitute_sku
        if not sku:
            raise ValidationError("An exact prescribed or approved substitute SKU is required.")
        if sku.tenant_id != episode.tenant_id:
            raise ValidationError("SKU is outside the dispensing tenant.")
        if item.is_controlled and not episode.pharmacy_location.controlled_drug_capability:
            raise ValidationError("Controlled medicine stock must be reserved from a secure location.")
        minimum_expiry = timezone.localdate() + timedelta(
            days=int(minimum_shelf_life_days or 0)
        )
        inventory_reservation = InventoryReservationService.reserve_stock(
            tenant=episode.tenant,
            branch=episode.branch,
            source_location=episode.pharmacy_location,
            sku=sku,
            requested_quantity=quantity,
            purpose="CLINICAL_DISPENSING",
            actor=actor,
            idempotency_key=f"clinical:{episode.id}:{idempotency_key}",
            minimum_expiry_date=minimum_expiry,
        )
        reservation = DispensingReservation.all_objects.create(
            tenant_id=episode.tenant_id,
            episode=episode,
            prescription_item=item,
            inventory_reservation=inventory_reservation,
            quantity=quantity,
            status=inventory_reservation.status,
            idempotency_key=idempotency_key,
        )
        _emit(
            "DispensingReservationCreated",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            prescription_item=item,
            episode=episode,
            medicine=item.canonical_medicine,
            sku=sku,
            quantity=quantity,
            unit=inventory_reservation.unit,
            reservation=str(reservation.id),
            inventory_reservation=str(inventory_reservation.id),
            substitution=str(getattr(substitution, "id", "") or ""),
        )
        return reservation


class DispensingAllocationService:
    @staticmethod
    @transaction.atomic
    def allocate(*, episode, actor):
        _require_capability(actor, episode.tenant_id, "dispensing.allocate")
        episode = DispensingEpisode.all_objects.select_for_update().get(
            id=episode.id,
            tenant_id=episode.tenant_id,
        )
        _active_verification(episode.prescription, lock=True)
        reservations = list(
            DispensingReservation.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
            ).select_related("inventory_reservation", "prescription_item")
        )
        if not reservations:
            raise ValidationError("Dispensing episode has no inventory reservations.")
        allocations = []
        created_any = False
        for reservation in reservations:
            ledger_entries = InventoryLedgerEntry.all_objects.filter(
                tenant_id=episode.tenant_id,
                source_document_type="RESERVATION",
                source_document_id=str(reservation.inventory_reservation_id),
                entry_type=InventoryLedgerEntry.EntryType.RESERVATION,
            ).select_related("inventory_batch", "location")
            for entry in ledger_entries:
                allocation, created = DispensingAllocation.all_objects.get_or_create(
                    tenant_id=episode.tenant_id,
                    episode=episode,
                    prescription_item=reservation.prescription_item,
                    reservation=reservation,
                    inventory_batch=entry.inventory_batch,
                    location=entry.location,
                    defaults={"quantity": entry.base_quantity_delta},
                )
                allocations.append(allocation)
                created_any = created_any or created
        if not allocations:
            raise ValidationError("Inventory reservation has no FEFO batch allocation.")
        if created_any:
            _emit(
                "DispensingAllocationCompleted",
                episode.prescription,
                actor=actor,
                patient=episode.patient,
                prescription=episode.prescription,
                episode=episode,
                allocation_count=len(allocations),
            )
        return allocations


class DispensingPreparationService:
    @staticmethod
    @transaction.atomic
    def prepare(*, episode, actor, quantities=None):
        _require_capability(actor, episode.tenant_id, "dispensing.prepare")
        episode = DispensingEpisode.all_objects.select_for_update().get(
            id=episode.id,
            tenant_id=episode.tenant_id,
        )
        _active_verification(episode.prescription, lock=True)
        if episode.status not in {"DRAFT", "PREPARING", "CHECKING"}:
            raise ValidationError("Dispensing episode cannot be prepared in its current state.")
        quantity_by_allocation = {
            str(allocation_id): Decimal(str(value))
            for allocation_id, value in (quantities or {}).items()
        }
        allocations = list(
            DispensingAllocation.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
            ).select_related(
                "prescription_item",
                "inventory_batch",
                "reservation__inventory_reservation__sku__package_definition",
            )
        )
        if not allocations:
            raise ValidationError("FEFO allocation must complete before preparation.")
        lines = []
        created_any = False
        for allocation in allocations:
            batch = allocation.inventory_batch
            if (
                batch.quality_status != InventoryBatch.QualityStatus.RELEASED
                or batch.recall_status != InventoryBatch.RecallStatus.NONE
                or batch.expiry_date < timezone.localdate()
            ):
                raise ValidationError("Allocated batch is not eligible for dispensing.")
            quantity = quantity_by_allocation.get(
                str(allocation.id),
                allocation.quantity,
            )
            if quantity <= 0 or quantity > allocation.quantity:
                raise ValidationError(
                    "Prepared quantity must be positive and within the FEFO allocation."
                )
            item = allocation.prescription_item
            supplied_sku = allocation.reservation.inventory_reservation.sku
            prescribed_sku = item.prescribed_sku or supplied_sku
            substitution = None
            if supplied_sku.id != prescribed_sku.id:
                substitution = ClinicalSubstitution.all_objects.filter(
                    tenant_id=episode.tenant_id,
                    prescription_item=item,
                    proposed_sku=supplied_sku,
                    status="APPROVED",
                ).first()
                if not substitution:
                    raise ValidationError("Prepared SKU lacks clinical substitution approval.")
            line, created = DispensingLine.all_objects.get_or_create(
                tenant_id=episode.tenant_id,
                episode=episode,
                inventory_allocation=allocation,
                defaults={
                    "prescription_item": item,
                    "prescribed_sku": prescribed_sku,
                    "supplied_sku": supplied_sku,
                    "inventory_batch": batch,
                    "quantity_authorized": allocation.quantity,
                    "quantity_prepared": quantity,
                    "unit": supplied_sku.package_definition.unit_of_measure,
                    "package_definition": supplied_sku.package_definition,
                    "batch_number_snapshot": batch.manufacturer_batch_number,
                    "expiry_date_snapshot": batch.expiry_date,
                    "dosage_label_instructions": item.dosage_instruction,
                    "substitution": substitution,
                    "status": "PREPARED",
                    "prepared_by": actor,
                },
            )
            if not created:
                if line.quantity_prepared != quantity:
                    raise ValidationError(
                        "Prepared allocation already exists with a different quantity."
                    )
            lines.append(line)
            created_any = created_any or created
        episode.status = "CHECKING"
        episode.save()
        _close_work_items(
            prescription=episode.prescription,
            episode=episode,
            queue_types=["DISPENSING_PREPARATION"],
        )
        _open_work_item(
            prescription=episode.prescription,
            episode=episode,
            queue_type="FINAL_CHECK",
            required_capability="dispensing.check",
        )
        if created_any:
            _emit(
                "DispensingStarted",
                episode.prescription,
                actor=actor,
                patient=episode.patient,
                prescription=episode.prescription,
                episode=episode,
            )
            _emit(
                "DispensingPrepared",
                episode.prescription,
                actor=actor,
                patient=episode.patient,
                prescription=episode.prescription,
                episode=episode,
                prepared_line_count=len(lines),
            )
            _store_clinical_document(
                prescription=episode.prescription,
                actor=actor,
                document_type="DISPENSING_WORKSHEET",
                document_number=f"WORKSHEET-{episode.dispensing_number}",
                source_id=episode.id,
                episode=episode,
                content={
                    "lines": [
                        {
                            "medicine": line.supplied_sku.display_name,
                            "quantity": line.quantity_prepared,
                            "unit": line.unit,
                            "instructions": line.dosage_label_instructions,
                            "batch": line.batch_number_snapshot,
                            "expiry": line.expiry_date_snapshot,
                        }
                        for line in lines
                    ],
                },
            )
        return lines


class DispensingCheckService:
    REQUIRED_CHECKS = {
        "patient",
        "medicine",
        "strength",
        "dosage_form",
        "quantity",
        "batch",
        "expiry",
        "instructions",
        "warnings",
        "package_integrity",
    }

    @classmethod
    @transaction.atomic
    def check(cls, *, episode, actor, checklist, notes=""):
        _require_capability(actor, episode.tenant_id, "dispensing.check")
        episode = DispensingEpisode.all_objects.select_for_update().get(
            id=episode.id,
            tenant_id=episode.tenant_id,
        )
        existing = DispensingCheck.all_objects.filter(
            tenant_id=episode.tenant_id,
            episode=episode,
        ).first()
        if existing:
            return existing
        _active_verification(episode.prescription, lock=True)
        lines = list(
            DispensingLine.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
            ).select_related("prescription_item", "inventory_batch")
        )
        if not lines:
            raise ValidationError("Prepared dispensing lines are required.")
        if any(line.prepared_by_id == actor.id for line in lines):
            raise ValidationError("The preparer cannot perform the independent final check.")
        missing_checks = sorted(
            check_name
            for check_name in cls.REQUIRED_CHECKS
            if not bool((checklist or {}).get(check_name))
        )
        if missing_checks:
            raise ValidationError(
                {"checklist": f"Required checks failed: {', '.join(missing_checks)}."}
            )
        if episode.prescription.is_controlled_medicine:
            _require_capability(
                actor,
                episode.tenant_id,
                "prescriptions.controlled_verify",
            )
            if not episode.pharmacy_location.controlled_drug_capability:
                raise ValidationError("Controlled stock is outside a secure location.")
        for line in lines:
            if line.inventory_batch.expiry_date < timezone.localdate():
                raise ValidationError("Expired batches cannot pass final check.")
            if line.quantity_prepared <= 0:
                raise ValidationError("All lines require a positive prepared quantity.")
        final_check = DispensingCheck.all_objects.create(
            tenant_id=episode.tenant_id,
            episode=episode,
            checked_by=actor,
            checklist=checklist,
            outcome="PASSED",
            notes=notes,
        )
        DispensingLine.all_objects.filter(
            tenant_id=episode.tenant_id,
            episode=episode,
        ).update(checker=actor, status="CHECKED")
        episode.status = "READY_FOR_SUPPLY"
        episode.save()
        _close_work_items(
            prescription=episode.prescription,
            episode=episode,
            queue_types=["FINAL_CHECK"],
        )
        _open_work_item(
            prescription=episode.prescription,
            episode=episode,
            queue_type="READY_FOR_COUNSELLING",
            required_capability="dispensing.counsel",
        )
        _emit(
            "DispensingChecked",
            episode.prescription,
            actor=actor,
            patient=episode.patient,
            prescription=episode.prescription,
            episode=episode,
            check=str(final_check.id),
        )
        _notify(
            prescription=episode.prescription,
            template_code="MEDICINE_READY",
            idempotency_key=f"medicine-ready:{episode.id}",
            payload={
                "prescription_reference": (
                    episode.prescription.prescription_number
                ),
                "action": "COUNSELLING_AND_COLLECTION",
            },
        )
        _notify(
            prescription=episode.prescription,
            template_code="PATIENT_COUNSELLING_REQUIRED",
            idempotency_key=f"counselling-required:{episode.id}",
            payload={
                "prescription_reference": (
                    episode.prescription.prescription_number
                ),
                "action": "COUNSELLING_PENDING",
            },
        )
        return final_check


class DispensingLabelService:
    @staticmethod
    @transaction.atomic
    def generate(*, dispensing_line, actor, label_size="PHARMACY_STANDARD"):
        _require_capability(actor, dispensing_line.tenant_id, "dispensing.prepare")
        line = DispensingLine.all_objects.select_for_update().select_related(
            "episode__patient",
            "episode__branch",
            "prescription_item",
            "supplied_sku",
            "inventory_batch",
        ).get(
            id=dispensing_line.id,
            tenant_id=dispensing_line.tenant_id,
        )
        warnings = list(
            ClinicalFinding.all_objects.filter(
                tenant_id=line.tenant_id,
                prescription=line.episode.prescription,
                resolution_status__in=["OPEN", "ACKNOWLEDGED", "OVERRIDDEN"],
            ).values_list("recommended_action", flat=True)
        )
        content = {
            "patient_name": line.episode.patient.full_name,
            "medicine_name": line.supplied_sku.display_name,
            "strength": line.prescription_item.strength_snapshot,
            "dosage_form": line.prescription_item.dosage_form_snapshot,
            "directions": line.dosage_label_instructions,
            "quantity": str(line.quantity_prepared),
            "unit": line.unit,
            "date": timezone.localdate().isoformat(),
            "pharmacy": line.episode.branch.name,
            "dispensing_number": line.episode.dispensing_number,
            "warnings": warnings,
            "storage_instructions": (
                line.episode.prescription.metadata or {}
            ).get("storage_instructions", ""),
            "batch": line.batch_number_snapshot,
            "expiry": line.expiry_date_snapshot.isoformat(),
            "dispenser": actor.get_full_name() or actor.username,
        }
        document_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True).encode()
        ).hexdigest()
        latest = (
            DispensingLabel.all_objects.filter(
                tenant_id=line.tenant_id,
                dispensing_line=line,
            )
            .order_by("-revision")
            .first()
        )
        if latest and latest.document_hash == document_hash:
            return latest
        revision = (latest.revision + 1) if latest else 1
        label = DispensingLabel.all_objects.create(
            tenant_id=line.tenant_id,
            episode=line.episode,
            dispensing_line=line,
            document_number=f"LBL-{line.episode.dispensing_number}-{revision}",
            revision=revision,
            label_size=label_size,
            content=content,
            document_hash=document_hash,
            barcode_payload=f"DWT:{line.episode_id}:{line.id}:R{revision}",
            generated_by=actor,
        )
        document = LocalClinicalObjectStorage.store(
            tenant_id=line.tenant_id,
            patient=line.episode.patient,
            original_name=f"{label.document_number}.txt",
            content_type="text/plain",
            content=json.dumps(content, sort_keys=True, indent=2).encode(),
            actor=actor,
        )
        document.metadata = {
            "document_type": "DISPENSING_LABEL",
            "document_number": label.document_number,
            "revision": label.revision,
            "prescription_id": str(line.episode.prescription_id),
            "dispensing_episode_id": str(line.episode_id),
            "dispensing_line_id": str(line.id),
            "document_hash": document_hash,
            "barcode_payload": label.barcode_payload,
        }
        document.save()
        label.stored_document = document
        label.save()
        _store_clinical_document(
            prescription=line.episode.prescription,
            actor=actor,
            document_type="PATIENT_MEDICATION_INFORMATION_SHEET",
            document_number=f"PMI-{line.episode.dispensing_number}-{line.id}",
            source_id=line.id,
            episode=line.episode,
            content={
                "medicine": line.supplied_sku.display_name,
                "strength": line.prescription_item.strength_snapshot,
                "dosage_form": line.prescription_item.dosage_form_snapshot,
                "quantity": line.quantity_prepared,
                "unit": line.unit,
                "instructions": line.dosage_label_instructions,
                "warnings": warnings,
                "storage": content["storage_instructions"],
                "batch": line.batch_number_snapshot,
                "expiry": line.expiry_date_snapshot,
            },
        )
        _emit(
            "DispensingLabelGenerated",
            line.episode.prescription,
            actor=actor,
            patient=line.episode.patient,
            prescription=line.episode.prescription,
            prescription_item=line.prescription_item,
            episode=line.episode,
            sku=line.supplied_sku,
            batch=line.inventory_batch,
            quantity=line.quantity_prepared,
            unit=line.unit,
            label=str(label.id),
            document_hash=document_hash,
        )
        return label


class PatientCounsellingService:
    @staticmethod
    @transaction.atomic
    def record(
        *,
        episode,
        actor,
        counselling_required,
        counselling_completed,
        refusal_reason="",
        **data,
    ):
        _require_capability(actor, episode.tenant_id, "dispensing.counsel")
        episode = DispensingEpisode.all_objects.select_for_update().get(
            id=episode.id,
            tenant_id=episode.tenant_id,
        )
        if counselling_required and not counselling_completed and not refusal_reason.strip():
            raise ValidationError(
                "Required counselling must be completed or explicitly refused."
            )
        counselled_at = (
            timezone.now()
            if counselling_completed or refusal_reason.strip()
            else None
        )
        counselling, _ = PatientCounselling.all_objects.update_or_create(
            tenant_id=episode.tenant_id,
            episode=episode,
            defaults={
                "patient": episode.patient,
                "counselling_required": counselling_required,
                "counselling_completed": counselling_completed,
                "refusal_reason": refusal_reason,
                "counselled_by": actor if counselled_at else None,
                "counselled_at": counselled_at,
                **data,
            },
        )
        episode.counselling_status = (
            "COMPLETED"
            if counselling_completed
            else "REFUSED"
            if refusal_reason.strip()
            else "NOT_REQUIRED"
        )
        episode.save()
        _close_work_items(
            prescription=episode.prescription,
            episode=episode,
            queue_types=["READY_FOR_COUNSELLING"],
        )
        _open_work_item(
            prescription=episode.prescription,
            episode=episode,
            queue_type="READY_FOR_SUPPLY",
            required_capability="dispensing.supply",
        )
        _emit(
            "PatientCounselled",
            episode.prescription,
            actor=actor,
            patient=episode.patient,
            prescription=episode.prescription,
            episode=episode,
            reason=refusal_reason,
            counselling=str(counselling.id),
            completed=counselling_completed,
        )
        _store_clinical_document(
            prescription=episode.prescription,
            actor=actor,
            document_type="COUNSELLING_ACKNOWLEDGEMENT",
            document_number=f"COUNSELLING-{episode.dispensing_number}",
            source_id=counselling.id,
            episode=episode,
            content={
                "counselling_required": counselling.counselling_required,
                "counselling_completed": counselling.counselling_completed,
                "refusal_reason": counselling.refusal_reason,
                "topics": counselling.topics,
                "warnings_explained": counselling.warnings_explained,
                "administration_instructions": (
                    counselling.administration_instructions
                ),
                "counselled_at": counselling.counselled_at,
            },
        )
        return counselling


class MedicationHistoryService:
    @staticmethod
    def record_supply(*, supply_line):
        item = supply_line.prescription_item
        history, created = PatientMedicationHistory.all_objects.get_or_create(
            tenant_id=supply_line.tenant_id,
            medicine_supply_line=supply_line,
            source="MEDICINE_SUPPLY",
            defaults={
                "patient": supply_line.supply.patient,
                "prescription": supply_line.supply.prescription,
                "prescription_item": item,
                "dispensing_episode": supply_line.supply.episode,
                "medicine_name_snapshot": item.prescribed_description_snapshot
                or item.medication_name,
                "supplied_sku": supply_line.supplied_sku,
                "active_ingredient_snapshot": item.active_ingredient_snapshot,
                "strength_snapshot": item.strength_snapshot,
                "dosage_form_snapshot": item.dosage_form_snapshot,
                "inventory_batch": supply_line.inventory_batch,
                "quantity": supply_line.quantity,
                "instructions": item.dosage_instruction,
                "supplied_at": supply_line.supply.supplied_at,
                "intended_start_date": item.start_date,
                "intended_end_date": item.end_date,
                "status": "ACTIVE",
            },
        )
        if created:
            _emit(
                "PatientMedicationHistoryRecorded",
                supply_line.supply.prescription,
                actor=supply_line.supply.supplied_by,
                patient=supply_line.supply.patient,
                prescription=supply_line.supply.prescription,
                prescription_item=item,
                episode=supply_line.supply.episode,
                medicine=item.canonical_medicine,
                sku=supply_line.supplied_sku,
                batch=supply_line.inventory_batch,
                quantity=supply_line.quantity,
                unit=supply_line.unit,
                medication_history=str(history.id),
            )
        return history

    @staticmethod
    def record_reversal(*, reversal, actor):
        original = PatientMedicationHistory.all_objects.filter(
            tenant_id=reversal.tenant_id,
            medicine_supply_line=reversal.original_supply_line,
            source="MEDICINE_SUPPLY",
        ).first()
        if not original:
            raise ValidationError("Original medication history is missing.")
        history, _ = PatientMedicationHistory.all_objects.get_or_create(
            tenant_id=reversal.tenant_id,
            medicine_supply_line=reversal.original_supply_line,
            source=f"DISPENSING_REVERSAL:{reversal.id}",
            defaults={
                "patient": original.patient,
                "prescription": original.prescription,
                "prescription_item": original.prescription_item,
                "dispensing_episode": original.dispensing_episode,
                "medicine_name_snapshot": original.medicine_name_snapshot,
                "supplied_sku": original.supplied_sku,
                "active_ingredient_snapshot": original.active_ingredient_snapshot,
                "strength_snapshot": original.strength_snapshot,
                "dosage_form_snapshot": original.dosage_form_snapshot,
                "inventory_batch": original.inventory_batch,
                "quantity": reversal.quantity,
                "instructions": original.instructions,
                "supplied_at": reversal.reversed_at,
                "intended_start_date": original.intended_start_date,
                "intended_end_date": original.intended_end_date,
                "status": "REVERSED",
                "reversal_reference": original,
            },
        )
        return history


class ControlledMedicineRegisterService:
    @staticmethod
    def post(*, supply_line, actor):
        prescription = supply_line.supply.prescription
        if not (
            prescription.is_controlled_medicine
            or supply_line.prescription_item.is_controlled
        ):
            return None
        identifier = (
            prescription.patient.identifiers.filter(
                verification_status="VERIFIED"
            )
            .order_by("created_at")
            .first()
        )
        _store_clinical_document(
            prescription=prescription,
            actor=actor,
            document_type="CONTROLLED_MEDICINE_SUPPLY_RECORD",
            document_number=(
                f"CONTROLLED-{supply_line.supply.supply_number}-"
                f"{supply_line.id}"
            ),
            source_id=supply_line.id,
            episode=supply_line.supply.episode,
            content={
                "medicine": (
                    supply_line.prescription_item.prescribed_description_snapshot
                    or supply_line.prescription_item.medication_name
                ),
                "quantity": supply_line.quantity,
                "unit": supply_line.unit,
                "instructions": (
                    supply_line.prescription_item.dosage_instruction
                ),
                "batch": supply_line.inventory_batch.manufacturer_batch_number,
                "expiry": supply_line.inventory_batch.expiry_date,
                "patient_identifier_reference": str(
                    getattr(identifier, "id", "") or ""
                ),
                "prescriber": prescription.practitioner.registration_number,
                "inventory_issue": supply_line.inventory_issue_id,
            },
        )
        return _emit(
            "ControlledMedicineSupplied",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            prescription_item=supply_line.prescription_item,
            episode=supply_line.supply.episode,
            medicine=supply_line.prescription_item.canonical_medicine,
            sku=supply_line.supplied_sku,
            batch=supply_line.inventory_batch,
            quantity=supply_line.quantity,
            unit=supply_line.unit,
            patient_identifier_reference=str(getattr(identifier, "id", "") or ""),
            prescriber=str(prescription.practitioner_id),
            pharmacist=str(actor.id),
            supply_date=supply_line.supply.supplied_at.isoformat(),
            register_category=(
                prescription.metadata or {}
            ).get("controlled_register_category", "CONFIGURED_POLICY"),
            running_balance_reference=str(supply_line.inventory_issue_id),
        )


class MedicineSupplyService:
    ALLOWED_PAYMENT_STATES = {"NOT_REQUIRED", "AUTHORIZED", "PAID", "WAIVED"}

    @staticmethod
    def _requested_lines(episode, line_quantities):
        lines = list(
            DispensingLine.all_objects.select_for_update()
            .filter(tenant_id=episode.tenant_id, episode=episode)
            .select_related(
                "prescription_item",
                "supplied_sku",
                "inventory_batch",
                "inventory_allocation__reservation__inventory_reservation",
            )
        )
        if line_quantities is None:
            return [
                (line, line.quantity_prepared - line.quantity_supplied)
                for line in lines
                if line.quantity_prepared > line.quantity_supplied
            ]
        by_id = {str(line.id): line for line in lines}
        requested = []
        for line_id, quantity in line_quantities.items():
            line = by_id.get(str(line_id))
            if not line:
                raise ValidationError("Dispensing line is outside the episode.")
            requested.append((line, Decimal(str(quantity))))
        return requested

    @classmethod
    @transaction.atomic
    def supply(
        cls,
        *,
        episode,
        actor,
        idempotency_key,
        line_quantities=None,
        partial_reason="",
        next_eligible_date=None,
    ):
        _require_capability(actor, episode.tenant_id, "dispensing.supply")
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})
        existing = MedicineSupply.all_objects.filter(
            tenant_id=episode.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        episode = DispensingEpisode.all_objects.select_for_update().select_related(
            "prescription__patient",
            "pharmacy_location",
            "branch",
        ).get(id=episode.id, tenant_id=episode.tenant_id)
        if episode.status not in {"READY_FOR_SUPPLY", "PARTIALLY_SUPPLIED"}:
            raise ValidationError("Episode is not ready for final supply.")
        prescription = episode.prescription
        _active_verification(prescription, lock=True)
        if prescription.expires_at and prescription.expires_at <= timezone.now():
            raise ValidationError("Expired prescriptions cannot be supplied.")
        if episode.payment_gate_state not in cls.ALLOWED_PAYMENT_STATES:
            raise ValidationError("Payment gate does not permit medicine supply.")
        final_check = DispensingCheck.all_objects.filter(
            tenant_id=episode.tenant_id,
            episode=episode,
            outcome="PASSED",
        ).first()
        if not final_check:
            raise ValidationError("Independent final check is required.")
        counselling = PatientCounselling.all_objects.filter(
            tenant_id=episode.tenant_id,
            episode=episode,
        ).first()
        if not counselling:
            raise ValidationError("Counselling status must be recorded before supply.")
        if (
            counselling.counselling_required
            and not counselling.counselling_completed
            and not counselling.refusal_reason
        ):
            raise ValidationError("Required counselling is incomplete.")
        if prescription.is_controlled_medicine:
            _require_capability(
                actor,
                episode.tenant_id,
                "prescriptions.controlled_verify",
            )
            if final_check.checked_by_id == actor.id:
                raise ValidationError(
                    "Controlled medicine supply requires separation from final check."
                )
            if not episode.pharmacy_location.controlled_drug_capability:
                raise ValidationError("Controlled medicine is outside secure custody.")
        requested_lines = cls._requested_lines(episode, line_quantities)
        if not requested_lines:
            raise ValidationError("No positive prepared quantity remains to supply.")
        supply = MedicineSupply.all_objects.create(
            tenant_id=episode.tenant_id,
            supply_number=f"SUP-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
            episode=episode,
            prescription=prescription,
            patient=episode.patient,
            supplied_by=actor,
            status="PARTIAL",
            idempotency_key=idempotency_key,
        )
        supply_lines = []
        repeat_dispensed = False
        for line, quantity in requested_lines:
            if quantity <= 0:
                raise ValidationError("Supply quantity must be positive.")
            if quantity > line.quantity_prepared - line.quantity_supplied:
                raise ValidationError("Supply exceeds the prepared quantity.")
            batch = line.inventory_batch
            if (
                batch.quality_status != InventoryBatch.QualityStatus.RELEASED
                or batch.recall_status != InventoryBatch.RecallStatus.NONE
                or batch.expiry_date < timezone.localdate()
            ):
                raise ValidationError("Batch is recalled, expired, or not quality released.")
            item = PrescriptionItem.all_objects.select_for_update().get(
                id=line.prescription_item_id,
                tenant_id=episode.tenant_id,
            )
            old_total = item.quantity_supplied_total
            authorized_remaining = item.total_authorized_quantity - old_total
            if quantity > authorized_remaining:
                raise ValidationError("Supply exceeds the remaining prescription authorization.")
            if old_total >= item.quantity:
                repeat_dispensed = True
                RepeatDispensingService.validate(
                    prescription_item=item,
                    actor=actor,
                )
            reservation = line.inventory_allocation.reservation.inventory_reservation
            InventoryReservationService.fulfill_reservation(
                reservation=reservation,
                quantity=quantity,
                inventory_batch=batch,
                actor=actor,
                idempotency_key=f"supply-release:{supply.id}:{line.id}",
            )
            inventory_issue = InventoryLedgerService.post_entry(
                tenant=episode.tenant,
                branch=episode.branch,
                location=episode.pharmacy_location,
                sku=line.supplied_sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.ISSUE,
                quantity_delta=-quantity,
                unit=line.unit,
                base_quantity_delta=-quantity,
                effective_timestamp=timezone.now(),
                source_document_type="MEDICINE_SUPPLY",
                source_document_id=str(supply.id),
                source_line_id=str(line.id),
                idempotency_key=f"medicine-supply:{supply.id}:{line.id}",
                actor=actor,
                reason_code="PATIENT_SUPPLY",
            )
            new_total = old_total + quantity
            outstanding = max(Decimal("0"), item.total_authorized_quantity - new_total)
            supply_line = MedicineSupplyLine.all_objects.create(
                tenant_id=episode.tenant_id,
                supply=supply,
                dispensing_line=line,
                prescription_item=item,
                supplied_sku=line.supplied_sku,
                inventory_batch=batch,
                quantity=quantity,
                unit=line.unit,
                outstanding_quantity=outstanding,
                partial_reason=partial_reason if outstanding else "",
                next_eligible_date=next_eligible_date if outstanding else None,
                inventory_issue=inventory_issue,
            )
            old_completed = int(old_total // item.quantity)
            new_completed = int(new_total // item.quantity)
            repeats_completed = max(0, new_completed - 1) - max(0, old_completed - 1)
            item.quantity_supplied_total = new_total
            if repeats_completed:
                item.repeats_remaining = max(
                    0,
                    item.repeats_remaining - repeats_completed,
                )
            if new_completed > old_completed and item.minimum_repeat_interval_days:
                item.earliest_refill_date = timezone.localdate() + timedelta(
                    days=item.minimum_repeat_interval_days
                )
            item.save()
            line.quantity_supplied += quantity
            line.status = (
                "SUPPLIED"
                if line.quantity_supplied >= line.quantity_prepared
                else "PARTIALLY_SUPPLIED"
            )
            line.save()
            MedicationHistoryService.record_supply(supply_line=supply_line)
            ControlledMedicineRegisterService.post(
                supply_line=supply_line,
                actor=actor,
            )
            supply_lines.append(supply_line)
        episode_complete = all(
            line.quantity_supplied >= line.quantity_prepared
            for line in DispensingLine.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode=episode,
            )
        )
        episode.status = "SUPPLIED" if episode_complete else "PARTIALLY_SUPPLIED"
        episode.completed_at = timezone.now() if episode_complete else None
        episode.save()
        prescription_items = list(
            PrescriptionItem.all_objects.filter(
                tenant_id=episode.tenant_id,
                prescription=prescription,
            )
        )
        prescription_complete = all(
            item.quantity_supplied_total >= item.total_authorized_quantity
            for item in prescription_items
        )
        partial_balance = any(
            item.quantity_supplied_total < item.quantity
            or (
                item.quantity
                and item.quantity_supplied_total % item.quantity != Decimal("0")
            )
            for item in prescription_items
        )
        prescription.dispensing_state = (
            "SUPPLIED" if prescription_complete else "PARTIALLY_SUPPLIED"
        )
        prescription.status = "SUPPLIED" if prescription_complete else "PARTIALLY_SUPPLIED"
        if prescription.repeat_authorization:
            prescription.repeats_remaining = min(
                item.repeats_remaining for item in prescription_items
            )
        prescription.save()
        supply.status = "COMPLETE" if episode_complete else "PARTIAL"
        supply.save()
        _close_work_items(
            prescription=prescription,
            episode=episode,
            queue_types=["READY_FOR_SUPPLY"],
        )
        if partial_balance:
            _open_work_item(
                prescription=prescription,
                episode=episode,
                queue_type="PARTIAL_DISPENSING_FOLLOW_UP",
                required_capability="dispensing.supply",
                due_at=(
                    timezone.make_aware(
                        datetime.combine(
                            next_eligible_date,
                            datetime.min.time(),
                        )
                    )
                    if next_eligible_date
                    else None
                ),
            )
            _store_clinical_document(
                prescription=prescription,
                actor=actor,
                document_type="PARTIAL_DISPENSING_BALANCE_RECORD",
                document_number=f"PARTIAL-{supply.supply_number}",
                source_id=supply.id,
                episode=episode,
                content={
                    "partial_reason": partial_reason,
                    "next_eligible_date": next_eligible_date,
                    "lines": [
                        {
                            "medicine": (
                                line.prescription_item.prescribed_description_snapshot
                                or line.prescription_item.medication_name
                            ),
                            "quantity_supplied": line.quantity,
                            "unit": line.unit,
                            "outstanding_quantity": line.outstanding_quantity,
                            "batch": (
                                line.inventory_batch.manufacturer_batch_number
                            ),
                            "expiry": line.inventory_batch.expiry_date,
                        }
                        for line in supply_lines
                    ],
                },
            )
        else:
            _close_work_items(
                prescription=prescription,
                episode=episode,
                queue_types=["PARTIAL_DISPENSING_FOLLOW_UP"],
            )
        if repeat_dispensed:
            _close_work_items(
                prescription=prescription,
                queue_types=["REPEAT_DUE", "EARLY_REPEAT_REVIEW"],
            )
        for item in prescription_items:
            if (
                item.repeats_remaining > 0
                and item.quantity_supplied_total >= item.quantity
                and item.quantity_supplied_total % item.quantity == Decimal("0")
            ):
                due_at = (
                    timezone.make_aware(
                        datetime.combine(
                            item.earliest_refill_date,
                            datetime.min.time(),
                        )
                    )
                    if item.earliest_refill_date
                    else timezone.now()
                )
                _open_work_item(
                    prescription=prescription,
                    queue_type="REPEAT_DUE",
                    required_capability="dispensing.repeat.authorize",
                    due_at=due_at,
                )
                _notify(
                    prescription=prescription,
                    template_code="REPEAT_DUE",
                    idempotency_key=(
                        f"repeat-due:{item.id}:{item.quantity_supplied_total}"
                    ),
                    payload={
                        "prescription_reference": (
                            prescription.prescription_number
                        ),
                        "eligible_date": (
                            item.earliest_refill_date.isoformat()
                            if item.earliest_refill_date
                            else timezone.localdate().isoformat()
                        ),
                    },
                )
        _emit(
            "MedicineSupplied",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            episode=episode,
            quantity=sum(
                (line.quantity for line in supply_lines),
                Decimal("0"),
            ),
            unit="MIXED" if len({line.unit for line in supply_lines}) > 1 else supply_lines[0].unit,
            supply=str(supply.id),
            inventory_issue_ids=[
                str(line.inventory_issue_id) for line in supply_lines
            ],
        )
        _emit(
            "PrescriptionFullyDispensed"
            if prescription_complete
            else "PrescriptionPartiallyDispensed",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            episode=episode,
            reason=partial_reason,
        )
        if repeat_dispensed:
            _emit(
                "RepeatDispensed",
                prescription,
                actor=actor,
                patient=prescription.patient,
                prescription=prescription,
                episode=episode,
            )
            _store_clinical_document(
                prescription=prescription,
                actor=actor,
                document_type="REPEAT_DISPENSING_RECORD",
                document_number=f"REPEAT-{supply.supply_number}",
                source_id=supply.id,
                episode=episode,
                content={
                    "supply_number": supply.supply_number,
                    "lines": [
                        {
                            "medicine": (
                                line.prescription_item.prescribed_description_snapshot
                                or line.prescription_item.medication_name
                            ),
                            "quantity": line.quantity,
                            "unit": line.unit,
                            "remaining_authorized_quantity": (
                                line.outstanding_quantity
                            ),
                            "batch": (
                                line.inventory_batch.manufacturer_batch_number
                            ),
                            "expiry": line.inventory_batch.expiry_date,
                        }
                        for line in supply_lines
                    ],
                },
            )
        if partial_balance:
            _notify(
                prescription=prescription,
                template_code="PARTIAL_SUPPLY",
                idempotency_key=f"partial-supply:{supply.id}",
                payload={
                    "prescription_reference": prescription.prescription_number,
                    "next_eligible_date": str(next_eligible_date or ""),
                },
            )
        return supply


class RepeatDispensingService:
    @staticmethod
    def validate(*, prescription_item, actor=None):
        if prescription_item.repeats_remaining <= 0:
            raise ValidationError("No repeat authorization remains.")
        today = timezone.localdate()
        if (
            prescription_item.earliest_refill_date
            and today < prescription_item.earliest_refill_date
            and not (
                actor
                and _has_capability(
                    actor,
                    prescription_item.tenant_id,
                    "dispensing.repeat.authorize",
                )
            )
        ):
            _open_work_item(
                prescription=prescription_item.prescription,
                queue_type="EARLY_REPEAT_REVIEW",
                required_capability="dispensing.repeat.authorize",
                due_at=timezone.make_aware(
                    datetime.combine(
                        prescription_item.earliest_refill_date,
                        datetime.min.time(),
                    )
                ),
            )
            _notify(
                prescription=prescription_item.prescription,
                template_code="REPEAT_TOO_EARLY",
                idempotency_key=(
                    f"repeat-too-early:{prescription_item.id}:"
                    f"{prescription_item.earliest_refill_date}"
                ),
                payload={
                    "prescription_reference": (
                        prescription_item.prescription.prescription_number
                    ),
                    "eligible_date": (
                        prescription_item.earliest_refill_date.isoformat()
                    ),
                },
            )
            raise ValidationError("Repeat is earlier than the authorized interval.")
        if (
            prescription_item.latest_refill_date
            and today > prescription_item.latest_refill_date
        ):
            raise ValidationError("Repeat authorization has expired.")
        _close_work_items(
            prescription=prescription_item.prescription,
            queue_types=["EARLY_REPEAT_REVIEW"],
        )
        return True


class ClinicalNotificationService:
    @staticmethod
    def medicine_unavailable(*, prescription):
        return _notify(
            prescription=prescription,
            template_code="MEDICINE_UNAVAILABLE",
            idempotency_key=f"medicine-unavailable:{prescription.id}",
            payload={
                "prescription_reference": prescription.prescription_number,
                "action": "CONTACT_PHARMACY",
            },
        )

    @staticmethod
    def recall_affecting_prior_supply(*, inventory_batch):
        notifications = []
        supply_lines = MedicineSupplyLine.all_objects.filter(
            tenant_id=inventory_batch.tenant_id,
            inventory_batch=inventory_batch,
        ).select_related("supply__prescription__patient")
        for supply_line in supply_lines:
            notification = _notify(
                prescription=supply_line.supply.prescription,
                template_code="RECALL_AFFECTING_PRIOR_SUPPLY",
                idempotency_key=f"clinical-recall:{supply_line.id}",
                payload={
                    "prescription_reference": (
                        supply_line.supply.prescription.prescription_number
                    ),
                    "supply_reference": supply_line.supply.supply_number,
                    "action": "CONTACT_PHARMACY_URGENTLY",
                },
            )
            if notification:
                notifications.append(notification)
        return notifications


class DispensingReversalService:
    @staticmethod
    @transaction.atomic
    def request_approval(*, supply_line, actor, reason):
        _require_capability(actor, supply_line.tenant_id, "dispensing.prepare")
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A reversal reason is required."})
        supply_line = MedicineSupplyLine.all_objects.select_related(
            "supply__prescription",
            "supply__episode",
        ).get(id=supply_line.id, tenant_id=supply_line.tenant_id)
        work_item = _open_work_item(
            prescription=supply_line.supply.prescription,
            episode=supply_line.supply.episode,
            queue_type="REVERSAL_APPROVAL",
            required_capability="dispensing.reverse",
        )
        _emit(
            "DispensingReversalRequested",
            supply_line.supply.prescription,
            actor=actor,
            patient=supply_line.supply.patient,
            prescription=supply_line.supply.prescription,
            prescription_item=supply_line.prescription_item,
            episode=supply_line.supply.episode,
            sku=supply_line.supplied_sku,
            batch=supply_line.inventory_batch,
            quantity=supply_line.quantity,
            unit=supply_line.unit,
            reason=reason,
            supply_line=str(supply_line.id),
        )
        return work_item

    @staticmethod
    @transaction.atomic
    def reverse(
        *,
        supply_line,
        actor,
        reason,
        idempotency_key,
        quantity=None,
        physically_returned=False,
        return_condition="",
        inventory_eligibility="QUARANTINE_REQUIRED",
    ):
        _require_capability(actor, supply_line.tenant_id, "dispensing.reverse")
        idempotency_key = str(idempotency_key or "").strip()
        existing = DispensingReversal.all_objects.filter(
            tenant_id=supply_line.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        supply_line = MedicineSupplyLine.all_objects.select_for_update().select_related(
            "supply__episode",
            "supply__prescription",
            "prescription_item",
        ).get(id=supply_line.id, tenant_id=supply_line.tenant_id)
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "A reversal reason is required."})
        reversal_quantity = Decimal(str(quantity or supply_line.quantity))
        previously_reversed = (
            DispensingReversal.all_objects.filter(
                tenant_id=supply_line.tenant_id,
                original_supply_line=supply_line,
            ).aggregate(total=Sum("quantity"))["total"]
            or Decimal("0")
        )
        if (
            reversal_quantity <= 0
            or previously_reversed + reversal_quantity > supply_line.quantity
        ):
            raise ValidationError("Reversal quantity exceeds the original supply.")
        prescription = supply_line.supply.prescription
        if prescription.is_controlled_medicine:
            _require_capability(
                actor,
                supply_line.tenant_id,
                "prescriptions.controlled_verify",
            )
        reversal = DispensingReversal.all_objects.create(
            tenant_id=supply_line.tenant_id,
            reversal_number=f"REV-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
            supply=supply_line.supply,
            original_supply_line=supply_line,
            quantity=reversal_quantity,
            reason=reason,
            authorized_by=actor,
            physically_returned=physically_returned,
            return_condition=return_condition,
            inventory_eligibility=inventory_eligibility,
            idempotency_key=idempotency_key,
        )
        MedicationHistoryService.record_reversal(reversal=reversal, actor=actor)
        item = PrescriptionItem.all_objects.select_for_update().get(
            id=supply_line.prescription_item_id,
            tenant_id=supply_line.tenant_id,
        )
        old_total = item.quantity_supplied_total
        old_completed_repeats = max(0, int(old_total // item.quantity) - 1)
        item.quantity_supplied_total = max(
            Decimal("0"),
            old_total - reversal_quantity,
        )
        new_completed_repeats = max(
            0,
            int(item.quantity_supplied_total // item.quantity) - 1,
        )
        restored_repeats = old_completed_repeats - new_completed_repeats
        if restored_repeats:
            item.repeats_remaining = min(
                item.refills_authorized,
                item.repeats_remaining + restored_repeats,
            )
        item.save()
        dispensing_line = DispensingLine.all_objects.select_for_update().get(
            id=supply_line.dispensing_line_id,
            tenant_id=supply_line.tenant_id,
        )
        dispensing_line.quantity_supplied = max(
            Decimal("0"),
            dispensing_line.quantity_supplied - reversal_quantity,
        )
        dispensing_line.status = (
            "PARTIALLY_SUPPLIED"
            if dispensing_line.quantity_supplied
            else "REVERSED"
        )
        dispensing_line.save()
        total_supply_quantity = (
            MedicineSupplyLine.all_objects.filter(
                tenant_id=supply_line.tenant_id,
                supply=supply_line.supply,
            ).aggregate(total=Sum("quantity"))["total"]
            or Decimal("0")
        )
        total_reversed_quantity = (
            DispensingReversal.all_objects.filter(
                tenant_id=supply_line.tenant_id,
                supply=supply_line.supply,
            ).aggregate(total=Sum("quantity"))["total"]
            or Decimal("0")
        )
        supply_line.supply.status = (
            "REVERSED"
            if total_reversed_quantity >= total_supply_quantity
            else "PARTIALLY_REVERSED"
        )
        supply_line.supply.save()
        if not MedicineSupply.all_objects.filter(
            tenant_id=supply_line.tenant_id,
            episode=supply_line.supply.episode,
        ).exclude(status="REVERSED").exists():
            supply_line.supply.episode.status = "REVERSED"
            supply_line.supply.episode.save()
        prescription_complete = all(
            prescription_item.quantity_supplied_total
            >= prescription_item.total_authorized_quantity
            for prescription_item in PrescriptionItem.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription=prescription,
            )
        )
        prescription.status = (
            "SUPPLIED" if prescription_complete else "PARTIALLY_SUPPLIED"
        )
        prescription.dispensing_state = (
            "SUPPLIED" if prescription_complete else "PARTIALLY_SUPPLIED"
        )
        if prescription.repeat_authorization:
            prescription.repeats_remaining = min(
                prescription_item.repeats_remaining
                for prescription_item in PrescriptionItem.all_objects.filter(
                    tenant_id=prescription.tenant_id,
                    prescription=prescription,
                )
            )
        prescription.save()
        if not prescription_complete:
            _open_work_item(
                prescription=prescription,
                queue_type="READY_FOR_DISPENSING",
                required_capability="dispensing.reserve",
            )
        _emit(
            "DispensingReversed",
            prescription,
            actor=actor,
            patient=prescription.patient,
            prescription=prescription,
            prescription_item=supply_line.prescription_item,
            episode=supply_line.supply.episode,
            medicine=supply_line.prescription_item.canonical_medicine,
            sku=supply_line.supplied_sku,
            batch=supply_line.inventory_batch,
            quantity=reversal_quantity,
            unit=supply_line.unit,
            reason=reason,
            reversal=str(reversal.id),
            inventory_action="RETURN_OR_QUALITY_WORKFLOW_REQUIRED",
        )
        _close_work_items(
            prescription=prescription,
            episode=supply_line.supply.episode,
            queue_types=["REVERSAL_APPROVAL"],
        )
        _store_clinical_document(
            prescription=prescription,
            actor=actor,
            document_type="DISPENSING_REVERSAL_RECORD",
            document_number=reversal.reversal_number,
            source_id=reversal.id,
            episode=supply_line.supply.episode,
            content={
                "original_supply": supply_line.supply.supply_number,
                "medicine": (
                    supply_line.prescription_item.prescribed_description_snapshot
                    or supply_line.prescription_item.medication_name
                ),
                "quantity": reversal.quantity,
                "unit": supply_line.unit,
                "reason": reversal.reason,
                "batch": supply_line.inventory_batch.manufacturer_batch_number,
                "expiry": supply_line.inventory_batch.expiry_date,
                "physically_returned": reversal.physically_returned,
                "inventory_eligibility": reversal.inventory_eligibility,
            },
        )
        return reversal


class PatientReturnService:
    @staticmethod
    @transaction.atomic
    def receive(
        *,
        supply,
        actor,
        quarantine_location,
        reason,
        lines,
        idempotency_key,
    ):
        _require_capability(actor, supply.tenant_id, "dispensing.return.receive")
        idempotency_key = str(idempotency_key or "").strip()
        existing = PatientReturn.all_objects.filter(
            tenant_id=supply.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        supply = MedicineSupply.all_objects.select_for_update().select_related(
            "patient",
            "prescription",
            "episode",
        ).get(id=supply.id, tenant_id=supply.tenant_id)
        if (
            quarantine_location.tenant_id != supply.tenant_id
            or quarantine_location.branch_id != supply.episode.branch_id
            or not (
                quarantine_location.quarantine_capability
                or quarantine_location.returns_capability
            )
        ):
            raise ValidationError(
                "Patient returns require a tenant-owned quarantine or returns location."
            )
        if not lines:
            raise ValidationError({"lines": "At least one return line is required."})
        patient_return = PatientReturn.all_objects.create(
            tenant_id=supply.tenant_id,
            return_number=f"RET-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
            supply=supply,
            patient=supply.patient,
            reason=reason,
            received_by=actor,
            quarantine_location=quarantine_location,
            idempotency_key=idempotency_key,
        )
        created_lines = []
        for values in lines:
            supply_line = MedicineSupplyLine.all_objects.select_for_update().get(
                id=values["supply_line_id"],
                tenant_id=supply.tenant_id,
                supply=supply,
            )
            quantity = Decimal(str(values["quantity"]))
            already_returned = (
                PatientReturnLine.all_objects.filter(
                    tenant_id=supply.tenant_id,
                    original_supply_line=supply_line,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            if quantity <= 0 or already_returned + quantity > supply_line.quantity:
                raise ValidationError("Patient return exceeds the supplied quantity.")
            if (
                supply.prescription.is_controlled_medicine
                or supply_line.prescription_item.is_controlled
            ):
                _require_capability(
                    actor,
                    supply.tenant_id,
                    "prescriptions.controlled_verify",
                )
            return_line = PatientReturnLine.all_objects.create(
                tenant_id=supply.tenant_id,
                patient_return=patient_return,
                original_supply_line=supply_line,
                inventory_batch=supply_line.inventory_batch,
                quantity=quantity,
                condition=values["condition"],
                notes=values.get("notes", ""),
            )
            original_history = PatientMedicationHistory.all_objects.filter(
                tenant_id=supply.tenant_id,
                medicine_supply_line=supply_line,
                source="MEDICINE_SUPPLY",
            ).first()
            if original_history:
                PatientMedicationHistory.all_objects.create(
                    tenant_id=supply.tenant_id,
                    patient=supply.patient,
                    prescription=supply.prescription,
                    prescription_item=supply_line.prescription_item,
                    dispensing_episode=supply.episode,
                    medicine_supply_line=supply_line,
                    medicine_name_snapshot=original_history.medicine_name_snapshot,
                    supplied_sku=supply_line.supplied_sku,
                    active_ingredient_snapshot=original_history.active_ingredient_snapshot,
                    strength_snapshot=original_history.strength_snapshot,
                    dosage_form_snapshot=original_history.dosage_form_snapshot,
                    inventory_batch=supply_line.inventory_batch,
                    quantity=quantity,
                    instructions=original_history.instructions,
                    supplied_at=timezone.now(),
                    intended_start_date=original_history.intended_start_date,
                    intended_end_date=original_history.intended_end_date,
                    status="RETURNED",
                    source=f"PATIENT_RETURN:{patient_return.id}",
                    reversal_reference=original_history,
                )
            created_lines.append(return_line)
        _open_work_item(
            prescription=supply.prescription,
            episode=supply.episode,
            queue_type="PATIENT_RETURN_INSPECTION",
            required_capability="dispensing.return.quality",
        )
        _emit(
            "PatientReturnReceived",
            supply.prescription,
            actor=actor,
            patient=supply.patient,
            prescription=supply.prescription,
            episode=supply.episode,
            reason=reason,
            patient_return=str(patient_return.id),
            quarantine_location=str(quarantine_location.id),
            returned_quantity=str(
                sum((line.quantity for line in created_lines), Decimal("0"))
            ),
        )
        _store_clinical_document(
            prescription=supply.prescription,
            actor=actor,
            document_type="PATIENT_RETURN_RECEIPT",
            document_number=patient_return.return_number,
            source_id=patient_return.id,
            episode=supply.episode,
            content={
                "original_supply": supply.supply_number,
                "reason": reason,
                "quarantine_location": quarantine_location.name,
                "lines": [
                    {
                        "medicine": (
                            line.original_supply_line.prescription_item
                            .prescribed_description_snapshot
                            or line.original_supply_line.prescription_item
                            .medication_name
                        ),
                        "quantity": line.quantity,
                        "unit": line.original_supply_line.unit,
                        "condition": line.condition,
                        "batch": (
                            line.inventory_batch.manufacturer_batch_number
                        ),
                        "expiry": line.inventory_batch.expiry_date,
                    }
                    for line in created_lines
                ],
            },
        )
        _notify(
            prescription=supply.prescription,
            template_code="PATIENT_RETURN_PENDING_INSPECTION",
            idempotency_key=f"return-pending-inspection:{patient_return.id}",
            payload={
                "prescription_reference": (
                    supply.prescription.prescription_number
                ),
                "return_reference": patient_return.return_number,
            },
        )
        return patient_return

    @staticmethod
    @transaction.atomic
    def inspect(
        *,
        patient_return,
        actor,
        quality_decision,
        destruction_path="",
        refund_eligibility="NOT_ELIGIBLE",
    ):
        _require_capability(
            actor,
            patient_return.tenant_id,
            "dispensing.return.quality",
        )
        patient_return = PatientReturn.all_objects.select_for_update().get(
            id=patient_return.id,
            tenant_id=patient_return.tenant_id,
        )
        if quality_decision == "SALEABLE_RESTOCK_APPROVED":
            if patient_return.received_by_id == actor.id:
                raise ValidationError(
                    "Return receiver cannot solely approve saleable restock."
                )
            _require_capability(
                actor,
                patient_return.tenant_id,
                "dispensing.return.restock",
            )
        if quality_decision == "DESTRUCTION_REQUIRED" and not destruction_path.strip():
            raise ValidationError("Destruction path is required.")
        patient_return.quality_decision = quality_decision
        patient_return.destruction_path = destruction_path
        patient_return.refund_eligibility = refund_eligibility
        patient_return.status = "INSPECTED"
        patient_return.inspected_by = actor
        patient_return.inspected_at = timezone.now()
        patient_return.save()
        _close_work_items(
            prescription=patient_return.supply.prescription,
            episode=patient_return.supply.episode,
            queue_types=["PATIENT_RETURN_INSPECTION"],
        )
        return patient_return


class DrugInteractionService:
    @staticmethod
    def screen(*, prescription, actor=None):
        return ClinicalDecisionSupportService.evaluate(
            prescription=prescription,
            actor=actor,
        )


class DoseValidationService:
    @staticmethod
    def validate(*, prescription, actor=None):
        return ClinicalDecisionSupportService.evaluate(
            prescription=prescription,
            actor=actor,
        )
