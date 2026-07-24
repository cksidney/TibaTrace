from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.patients.models import (
    Patient,
    PatientAllergy,
    PatientClinicalSummary,
    PatientIdentifier,
)
from apps.workflows.service import emit_event


def _has_capability(actor, tenant_id, *capabilities):
    return bool(
        actor
        and any(
            actor.has_capability(capability, tenant_id=tenant_id)
            for capability in capabilities
        )
    )


def _require_capability(actor, tenant_id, *capabilities):
    if not _has_capability(actor, tenant_id, *capabilities):
        raise PermissionDenied(f"Capability {capabilities[0]} is required.")


class PatientIdentifierProtector:
    @staticmethod
    def _fernet(tenant_id):
        material = f"{settings.SECRET_KEY}:patient-identifier:{tenant_id}".encode()
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))

    @staticmethod
    def normalize(value):
        return "".join(str(value or "").strip().upper().split())

    @classmethod
    def digest(cls, *, tenant_id, identifier_type, value):
        normalized = f"{identifier_type}:{cls.normalize(value)}".encode()
        key = f"{settings.SECRET_KEY}:{tenant_id}".encode()
        return hmac.new(key, normalized, hashlib.sha256).hexdigest()

    @classmethod
    def protect(cls, *, tenant_id, value):
        normalized = cls.normalize(value)
        if not normalized:
            raise ValidationError({"value": "An identifier value is required."})
        return cls._fernet(tenant_id).encrypt(normalized.encode()).decode()

    @classmethod
    def reveal(cls, *, tenant_id, protected_value):
        try:
            return cls._fernet(tenant_id).decrypt(protected_value.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise ValidationError("The protected identifier cannot be decrypted.") from exc


class PatientGovernanceService:
    @staticmethod
    @transaction.atomic
    def create_patient(*, tenant, actor, patient_number, internal_reference_id, **data):
        _require_capability(actor, tenant.id, "patients.create", "patients.write")
        patient_number = str(patient_number or "").strip()
        internal_reference_id = str(internal_reference_id or "").strip()
        if not patient_number or not internal_reference_id:
            raise ValidationError(
                {
                    "patient_number": "Patient number is required.",
                    "internal_reference_id": "Internal reference is required.",
                }
            )
        patient = Patient.all_objects.create(
            tenant=tenant,
            patient_number=patient_number,
            internal_reference_id=internal_reference_id,
            created_by=actor,
            **data,
        )
        log_audit(
            tenant_id=tenant.id,
            action="PATIENT_CREATED",
            model_name="Patient",
            object_id=patient.id,
            actor_id=actor.id,
            metadata={"patient_number": patient.patient_number},
        )
        emit_event(
            tenant_id=tenant.id,
            aggregate_type="Patient",
            aggregate_id=patient.id,
            event_type="PatientCreated",
            payload={
                "tenant": str(tenant.id),
                "actor": str(actor.id),
                "patient": str(patient.id),
                "event_version": 1,
                "timestamp": timezone.now().isoformat(),
            },
        )
        return patient

    @staticmethod
    @transaction.atomic
    def add_identifier(
        *,
        patient,
        actor,
        identifier_type,
        value,
        system="",
        verification_status="UNVERIFIED",
        issuing_authority="",
        issue_date=None,
        expiry_date=None,
    ):
        _require_capability(
            actor,
            patient.tenant_id,
            "patients.identity.manage",
            "patients.write",
        )
        identifier_type = str(identifier_type or "OTHER").upper()
        normalized = PatientIdentifierProtector.normalize(value)
        identifier = PatientIdentifier.all_objects.create(
            tenant_id=patient.tenant_id,
            patient=patient,
            system=system or identifier_type,
            value="",
            identifier_type=identifier_type,
            value_hash=PatientIdentifierProtector.digest(
                tenant_id=patient.tenant_id,
                identifier_type=identifier_type,
                value=normalized,
            ),
            protected_value=PatientIdentifierProtector.protect(
                tenant_id=patient.tenant_id,
                value=normalized,
            ),
            last_four=normalized[-4:],
            verification_status=verification_status,
            issuing_authority=issuing_authority,
            issue_date=issue_date,
            expiry_date=expiry_date,
            verified_by=actor if verification_status == "VERIFIED" else None,
        )
        log_audit(
            tenant_id=patient.tenant_id,
            action="PATIENT_IDENTIFIER_ADDED",
            model_name="PatientIdentifier",
            object_id=identifier.id,
            actor_id=actor.id,
            metadata={
                "patient_id": str(patient.id),
                "identifier_type": identifier_type,
                "masked_value": identifier.masked_value,
            },
        )
        return identifier

    @staticmethod
    def reveal_identifier(*, identifier, actor, reason):
        _require_capability(
            actor,
            identifier.tenant_id,
            "patients.identity.view",
            "patients.sensitive.view",
        )
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError({"reason": "An access reason is required."})
        value = PatientIdentifierProtector.reveal(
            tenant_id=identifier.tenant_id,
            protected_value=identifier.protected_value,
        )
        log_audit(
            tenant_id=identifier.tenant_id,
            action="PATIENT_IDENTIFIER_REVEALED",
            model_name="PatientIdentifier",
            object_id=identifier.id,
            actor_id=actor.id,
            metadata={"reason": reason, "patient_id": str(identifier.patient_id)},
        )
        return value

    @staticmethod
    @transaction.atomic
    def record_allergy(*, patient, actor, **data):
        _require_capability(
            actor,
            patient.tenant_id,
            "patients.allergy.record",
            "patients.write",
        )
        allergy = PatientAllergy.all_objects.create(
            tenant_id=patient.tenant_id,
            patient=patient,
            recorded_by=actor,
            **data,
        )
        log_audit(
            tenant_id=patient.tenant_id,
            action="PATIENT_ALLERGY_RECORDED",
            model_name="PatientAllergy",
            object_id=allergy.id,
            actor_id=actor.id,
            metadata={"patient_id": str(patient.id), "severity": allergy.severity},
        )
        emit_event(
            tenant_id=patient.tenant_id,
            aggregate_type="Patient",
            aggregate_id=patient.id,
            event_type="PatientAllergyRecorded",
            payload={
                "tenant": str(patient.tenant_id),
                "actor": str(actor.id),
                "patient": str(patient.id),
                "allergy": str(allergy.id),
                "event_version": 1,
                "timestamp": timezone.now().isoformat(),
            },
        )
        return allergy


class PatientClinicalSummaryService:
    @staticmethod
    @transaction.atomic
    def update_summary(*, patient, actor, source, verification_status, **data):
        _require_capability(
            actor,
            patient.tenant_id,
            "patients.clinical_summary.manage",
            "patients.write",
        )
        summary, _ = PatientClinicalSummary.all_objects.update_or_create(
            tenant_id=patient.tenant_id,
            patient=patient,
            defaults={
                **data,
                "source": source,
                "verification_status": verification_status,
                "verified_by": actor
                if verification_status == "CLINICIAN_VERIFIED"
                else None,
                "verified_at": timezone.now()
                if verification_status == "CLINICIAN_VERIFIED"
                else None,
            },
        )
        log_audit(
            tenant_id=patient.tenant_id,
            action="PATIENT_CLINICAL_SUMMARY_UPDATED",
            model_name="PatientClinicalSummary",
            object_id=summary.id,
            actor_id=actor.id,
            metadata={"patient_id": str(patient.id), "source": source},
        )
        return summary
