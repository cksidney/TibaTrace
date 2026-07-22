from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.clinical.models import (
    ClinicalCondition,
    ClinicalDiagnosticReport,
    ClinicalDocument,
    ClinicalEncounter,
    ClinicalObservation,
    MedicationAdministrationRecord,
)
from apps.fhir.exceptions import (
    FHIRBusinessRuleError,
    FHIRReferenceResolutionError,
    FHIRSecurityError,
    FHIRValidationError,
)
from apps.organizations.models import Organization
from apps.patients.models import Patient, PatientAllergy, PatientMedication
from apps.practitioners.models import Practitioner


class ClinicalDomainService:
    """Tenant-safe command boundary for persisted clinical records."""

    ENCOUNTER_TRANSITIONS = {
        "PLANNED": {"ARRIVED", "IN_PROGRESS", "CANCELLED", "ENTERED_IN_ERROR"},
        "ARRIVED": {"TRIAGED", "IN_PROGRESS", "CANCELLED", "ENTERED_IN_ERROR"},
        "TRIAGED": {"IN_PROGRESS", "CANCELLED", "ENTERED_IN_ERROR"},
        "IN_PROGRESS": {"ONLEAVE", "FINISHED", "CANCELLED", "ENTERED_IN_ERROR"},
        "ONLEAVE": {"IN_PROGRESS", "FINISHED", "CANCELLED", "ENTERED_IN_ERROR"},
        "FINISHED": {"ENTERED_IN_ERROR"},
        "CANCELLED": {"ENTERED_IN_ERROR"},
        "ENTERED_IN_ERROR": set(),
    }
    OBSERVATION_TRANSITIONS = {
        "REGISTERED": {"PRELIMINARY", "FINAL", "CANCELLED", "ENTERED_IN_ERROR"},
        "PRELIMINARY": {"FINAL", "AMENDED", "CORRECTED", "CANCELLED", "ENTERED_IN_ERROR"},
        "FINAL": {"AMENDED", "CORRECTED", "ENTERED_IN_ERROR"},
        "AMENDED": {"CORRECTED", "ENTERED_IN_ERROR"},
        "CORRECTED": {"AMENDED", "ENTERED_IN_ERROR"},
        "CANCELLED": {"ENTERED_IN_ERROR"},
        "UNKNOWN": {"REGISTERED", "PRELIMINARY", "FINAL", "CANCELLED", "ENTERED_IN_ERROR"},
        "ENTERED_IN_ERROR": set(),
    }
    REPORT_TRANSITIONS = {
        "REGISTERED": {"PARTIAL", "PRELIMINARY", "FINAL", "CANCELLED", "ENTERED_IN_ERROR"},
        "PARTIAL": {"PRELIMINARY", "FINAL", "CANCELLED", "ENTERED_IN_ERROR"},
        "PRELIMINARY": {"FINAL", "AMENDED", "CORRECTED", "CANCELLED", "ENTERED_IN_ERROR"},
        "FINAL": {"AMENDED", "CORRECTED", "APPENDED", "ENTERED_IN_ERROR"},
        "AMENDED": {"CORRECTED", "APPENDED", "ENTERED_IN_ERROR"},
        "CORRECTED": {"AMENDED", "APPENDED", "ENTERED_IN_ERROR"},
        "APPENDED": {"AMENDED", "CORRECTED", "ENTERED_IN_ERROR"},
        "CANCELLED": {"ENTERED_IN_ERROR"},
        "UNKNOWN": {"REGISTERED", "PARTIAL", "PRELIMINARY", "FINAL", "CANCELLED", "ENTERED_IN_ERROR"},
        "ENTERED_IN_ERROR": set(),
    }
    DOCUMENT_TRANSITIONS = {
        "CURRENT": {"SUPERSEDED", "ENTERED_IN_ERROR"},
        "SUPERSEDED": {"ENTERED_IN_ERROR"},
        "ENTERED_IN_ERROR": set(),
    }
    ADMINISTRATION_TRANSITIONS = {
        "IN_PROGRESS": {"ON_HOLD", "COMPLETED", "NOT_DONE", "STOPPED", "ENTERED_IN_ERROR"},
        "ON_HOLD": {"IN_PROGRESS", "COMPLETED", "NOT_DONE", "STOPPED", "ENTERED_IN_ERROR"},
        "COMPLETED": {"ENTERED_IN_ERROR"},
        "NOT_DONE": {"ENTERED_IN_ERROR"},
        "STOPPED": {"ENTERED_IN_ERROR"},
        "UNKNOWN": {"IN_PROGRESS", "ON_HOLD", "COMPLETED", "NOT_DONE", "STOPPED", "ENTERED_IN_ERROR"},
        "ENTERED_IN_ERROR": set(),
    }

    @staticmethod
    def _require_tenant_id(tenant_id: str | None) -> str:
        value = str(tenant_id or "").strip()
        if not value:
            raise FHIRSecurityError("Missing tenant context.", code="forbidden")
        return value

    @staticmethod
    def _required_text(command: dict, key: str, label: str) -> str:
        value = str(command.get(key) or "").strip()
        if not value:
            raise FHIRValidationError(f"{label} is required.", expression=key)
        return value

    @staticmethod
    def _choice(model, field_name: str, value, label: str) -> str:
        normalized = str(value or "").strip().upper().replace("-", "_")
        allowed = {choice[0] for choice in model._meta.get_field(field_name).choices}
        if normalized not in allowed:
            raise FHIRValidationError(
                f"Unsupported {label}.",
                diagnostics=f"Allowed values: {', '.join(sorted(allowed))}",
                expression=field_name,
            )
        return normalized

    @staticmethod
    def _datetime(value, field_name: str, *, required: bool = False):
        if value in (None, ""):
            if required:
                raise FHIRValidationError(f"{field_name} is required.", expression=field_name)
            return None
        parsed = value if isinstance(value, datetime) else parse_datetime(str(value))
        if parsed is None:
            raise FHIRValidationError(
                f"{field_name} must be a valid FHIR dateTime.",
                expression=field_name,
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @staticmethod
    def _resource_id(command: dict):
        value = command.get("id")
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise FHIRValidationError("Resource id must be a UUID.", expression="id") from exc

    @staticmethod
    def _save(instance):
        try:
            instance.full_clean()
            instance.save()
        except DjangoValidationError as exc:
            fields = sorted(getattr(exc, "message_dict", {}) or {})
            raise FHIRValidationError(
                "Clinical domain validation failed.",
                diagnostics=f"Invalid fields: {', '.join(fields)}" if fields else "The record is invalid.",
            ) from exc
        return instance

    @staticmethod
    def _transition(current: str, requested: str, transitions: dict[str, set[str]], label: str) -> None:
        if current == requested:
            return
        if requested not in transitions.get(current, set()):
            raise FHIRBusinessRuleError(
                f"Invalid {label} status transition.",
                diagnostics=f"Transition from {current} to {requested} is not allowed.",
                code="business-rule",
            )

    @staticmethod
    def _owned_reference(model, resource_id, tenant_id: str, label: str):
        if not resource_id:
            return None
        try:
            manager = getattr(model, "all_objects", model.objects)
            instance = manager.filter(id=resource_id, tenant_id=tenant_id).first()
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise FHIRReferenceResolutionError(
                f"Invalid {label} reference.",
                code="not-found",
            ) from exc
        if not instance:
            raise FHIRReferenceResolutionError(
                f"Referenced {label} is not available in the active tenant.",
                code="not-found",
            )
        return instance

    @classmethod
    def _patient_reference(cls, patient_id, tenant_id: str) -> Patient:
        if not patient_id:
            raise FHIRValidationError("Patient reference is required.", expression="patient")
        return cls._owned_reference(Patient, patient_id, tenant_id, "Patient")

    @classmethod
    def _pharmacy_patient(cls, patient_id, tenant_id: str) -> Patient:
        if not patient_id:
            raise FHIRValidationError("Patient reference is required.", expression="patient")
        try:
            patient = Patient.all_objects.filter(id=patient_id, tenant_id=tenant_id).first()
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise FHIRReferenceResolutionError("Invalid Patient reference.", code="not-found") from exc
        if not patient:
            raise FHIRReferenceResolutionError(
                "Referenced Patient is not available in the active tenant.",
                code="not-found",
            )
        return patient

    @classmethod
    def _clinical_record(cls, model, resource_id, tenant_id: str, label: str, operation: str | None = None):
        if not resource_id:
            return None
        try:
            instance = model.all_objects.select_for_update().filter(
                id=resource_id,
                tenant_id=tenant_id,
            ).first()
            if instance:
                return instance
            if operation != "create":
                raise FHIRReferenceResolutionError(
                    f"{label} is not available in the active tenant.",
                    code="not-found",
                )
        except FHIRReferenceResolutionError:
            raise
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise FHIRValidationError("Resource id must be a UUID.", expression="id") from exc
        return None

    @classmethod
    def _encounter(cls, encounter_id, tenant_id: str, patient_id=None):
        if not encounter_id:
            return None
        encounter = cls._clinical_record(ClinicalEncounter, encounter_id, tenant_id, "Encounter")
        if not encounter:
            raise FHIRReferenceResolutionError(
                "Referenced Encounter is not available in the active tenant.",
                code="not-found",
            )
        if patient_id and str(encounter.patient_id) != str(patient_id):
            raise FHIRBusinessRuleError(
                "Encounter and clinical record must reference the same patient.",
                code="business-rule",
            )
        return encounter

    @staticmethod
    def _assert_patient_immutable(instance, patient: Patient) -> None:
        if instance and str(instance.patient_id) != str(patient.id):
            raise FHIRBusinessRuleError(
                "The patient of an existing clinical record cannot be changed.",
                code="business-rule",
            )

    @classmethod
    def process_patient_allergy(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._pharmacy_patient(command.get("patient_id"), tenant_id)
        allergen_name = cls._required_text(command, "allergen_name", "Allergen")
        severity = cls._choice(PatientAllergy, "severity", command.get("severity"), "allergy severity")
        resource_id = cls._resource_id(command)

        with transaction.atomic():
            allergy = None
            if resource_id:
                allergy = PatientAllergy.all_objects.select_for_update().filter(
                    id=resource_id,
                    tenant_id=tenant_id,
                ).first()
                if not allergy and command.get("_operation") != "create":
                    raise FHIRReferenceResolutionError(
                        "Allergy is not available in the active tenant.",
                        code="not-found",
                    )
            if allergy and str(allergy.patient_id) != str(patient.id):
                raise FHIRBusinessRuleError(
                    "The patient of an existing allergy cannot be changed.",
                    code="business-rule",
                )
            if not allergy:
                allergy = PatientAllergy(
                    id=resource_id or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            allergy.allergen_name = allergen_name
            allergy.severity = severity
            allergy.is_active = bool(command.get("is_active", True))
            allergy.reaction = str(command.get("reaction") or "").strip()
            allergy.notes = str(command.get("notes") or "").strip()
            return cls._save(allergy)

    @classmethod
    def process_condition(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(ClinicalCondition, "clinical_status", command.get("clinical_status"), "clinical status")
        verification = cls._choice(
            ClinicalCondition,
            "verification_status",
            command.get("verification_status"),
            "verification status",
        )
        code = cls._required_text(command, "code", "Condition code")
        encounter = cls._encounter(command.get("encounter_id"), tenant_id, patient.id)
        onset = cls._datetime(command.get("onset_date"), "onset_date")
        if onset and onset > timezone.now():
            raise FHIRBusinessRuleError("Condition onset cannot be in the future.", code="business-rule")
        if verification in {"REFUTED", "ENTERED_IN_ERROR"} and status in {"ACTIVE", "RECURRENCE", "RELAPSE"}:
            raise FHIRBusinessRuleError(
                "A refuted or entered-in-error condition cannot remain clinically active.",
                code="business-rule",
            )

        with transaction.atomic():
            condition = cls._clinical_record(
                ClinicalCondition,
                cls._resource_id(command),
                tenant_id,
                "Condition",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(condition, patient)
            if not condition:
                condition = ClinicalCondition(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            condition.encounter = encounter
            condition.clinical_status = status
            condition.verification_status = verification
            condition.category = command.get("category") or None
            condition.code = code
            condition.system = command.get("system") or None
            condition.display = command.get("display") or None
            condition.onset_date = onset
            return cls._save(condition)

    @classmethod
    def process_encounter(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(ClinicalEncounter, "status", command.get("status"), "encounter status")
        encounter_class = cls._required_text(command, "encounter_class", "Encounter class").upper()
        if encounter_class not in {"AMB", "EMER", "FLD", "HH", "IMP", "OBSENC", "PRENC", "SS", "VR"}:
            raise FHIRValidationError("Unsupported encounter class.", expression="encounter_class")
        start = cls._datetime(command.get("start_time"), "start_time")
        end = cls._datetime(command.get("end_time"), "end_time")
        if start and end and end < start:
            raise FHIRBusinessRuleError("Encounter end cannot precede its start.", code="business-rule")
        if status == "FINISHED" and not end:
            raise FHIRBusinessRuleError("A finished encounter requires an end time.", code="business-rule")
        organization = cls._owned_reference(
            Organization,
            command.get("organization_id") or command.get("facility_id"),
            tenant_id,
            "Organization",
        )
        practitioner = cls._owned_reference(
            Practitioner,
            command.get("practitioner_id"),
            tenant_id,
            "Practitioner",
        )

        with transaction.atomic():
            encounter = cls._clinical_record(
                ClinicalEncounter,
                cls._resource_id(command),
                tenant_id,
                "Encounter",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(encounter, patient)
            if encounter:
                cls._transition(encounter.status, status, cls.ENCOUNTER_TRANSITIONS, "encounter")
            else:
                encounter = ClinicalEncounter(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            encounter.status = status
            encounter.encounter_class = encounter_class
            encounter.start_time = start
            encounter.end_time = end
            encounter.reason_code = command.get("reason_code") or None
            encounter.organization = organization
            encounter.practitioner = practitioner
            return cls._save(encounter)

    @classmethod
    def process_medication_statement(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._pharmacy_patient(command.get("patient_id"), tenant_id)
        status = cls._choice(
            PatientMedication,
            "status",
            command.get("status"),
            "medication statement status",
        )
        resource_id = cls._resource_id(command)
        with transaction.atomic():
            profile = None
            if resource_id:
                profile = PatientMedication.all_objects.select_for_update().filter(
                    id=resource_id,
                    tenant_id=tenant_id,
                ).first()
                if not profile and command.get("_operation") != "create":
                    raise FHIRReferenceResolutionError(
                        "MedicationStatement is not available in the active tenant.",
                        code="not-found",
                    )
            if profile and str(profile.patient_id) != str(patient.id):
                raise FHIRBusinessRuleError(
                    "The patient of an existing medication statement cannot be changed.",
                    code="business-rule",
                )
            if not profile:
                profile = PatientMedication(
                    id=resource_id or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            profile.status = status
            profile.directions = str(command.get("directions") or "").strip()
            profile.medicine_id = command.get("medicine_id") or command.get("item_id")
            profile.medication_name = cls._required_text(command, "medication_name", "Medication")
            return cls._save(profile)

    @classmethod
    def process_medication_administration(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(
            MedicationAdministrationRecord,
            "status",
            command.get("status"),
            "administration status",
        )
        medication_name = cls._required_text(command, "medication_name", "Medication")
        effective = cls._datetime(
            command.get("effective_time"),
            "effective_time",
            required=True,
        )
        reason_not_done = str(command.get("reason_not_done") or "").strip()
        if status == "NOT_DONE" and not reason_not_done:
            raise FHIRBusinessRuleError(
                "A not-done administration requires a reason.",
                code="business-rule",
            )
        encounter = cls._encounter(command.get("encounter_id"), tenant_id, patient.id)
        performer = cls._owned_reference(
            Practitioner,
            command.get("performer_id"),
            tenant_id,
            "Practitioner",
        )

        with transaction.atomic():
            administration = cls._clinical_record(
                MedicationAdministrationRecord,
                cls._resource_id(command),
                tenant_id,
                "MedicationAdministration",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(administration, patient)
            if administration:
                cls._transition(
                    administration.status,
                    status,
                    cls.ADMINISTRATION_TRANSITIONS,
                    "medication administration",
                )
            else:
                administration = MedicationAdministrationRecord(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            administration.status = status
            administration.medication_name = medication_name
            administration.encounter = encounter
            administration.effective_time = effective
            administration.dosage_text = command.get("dosage_text") or None
            administration.performer = performer
            administration.reason_not_done = reason_not_done or None
            return cls._save(administration)

    @classmethod
    def process_observation(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(ClinicalObservation, "status", command.get("status"), "observation status")
        code = cls._required_text(command, "code", "Observation code")
        encounter = cls._encounter(command.get("encounter_id"), tenant_id, patient.id)
        effective = cls._datetime(
            command.get("effective_time"),
            "effective_time",
            required=status in {"FINAL", "AMENDED", "CORRECTED"},
        )
        quantity_raw = command.get("value_quantity")
        value_string = str(command.get("value_string") or "").strip() or None
        if (quantity_raw is None) == (value_string is None):
            raise FHIRBusinessRuleError(
                "Observation requires exactly one supported value type.",
                diagnostics="Provide valueQuantity or valueString, but not both.",
                code="business-rule",
            )
        quantity = None
        if quantity_raw is not None:
            try:
                quantity = Decimal(str(quantity_raw))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise FHIRValidationError("Observation quantity is invalid.", expression="value_quantity") from exc
            if not str(command.get("value_unit") or "").strip():
                raise FHIRBusinessRuleError(
                    "A quantitative observation requires a unit.",
                    code="business-rule",
                )

        with transaction.atomic():
            observation = cls._clinical_record(
                ClinicalObservation,
                cls._resource_id(command),
                tenant_id,
                "Observation",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(observation, patient)
            if observation:
                cls._transition(observation.status, status, cls.OBSERVATION_TRANSITIONS, "observation")
            else:
                observation = ClinicalObservation(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            observation.encounter = encounter
            observation.status = status
            observation.category = command.get("category") or None
            observation.code = code
            observation.system = command.get("system") or None
            observation.display = command.get("display") or None
            observation.effective_time = effective
            observation.value_quantity = quantity
            observation.value_unit = command.get("value_unit") or None
            observation.value_string = value_string
            observation.interpretation = command.get("interpretation") or None
            return cls._save(observation)

    @classmethod
    def _observations(cls, observation_ids, tenant_id: str, patient_id) -> list[ClinicalObservation]:
        resolved = []
        for observation_id in observation_ids or []:
            observation = cls._clinical_record(
                ClinicalObservation,
                observation_id,
                tenant_id,
                "Observation",
            )
            if not observation:
                raise FHIRReferenceResolutionError(
                    "Referenced Observation is not available in the active tenant.",
                    code="not-found",
                )
            if str(observation.patient_id) != str(patient_id):
                raise FHIRBusinessRuleError(
                    "DiagnosticReport results must belong to the report patient.",
                    code="business-rule",
                )
            resolved.append(observation)
        return resolved

    @classmethod
    def process_diagnostic_report(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(
            ClinicalDiagnosticReport,
            "status",
            command.get("status"),
            "diagnostic report status",
        )
        code = cls._required_text(command, "code", "Diagnostic report code")
        encounter = cls._encounter(command.get("encounter_id"), tenant_id, patient.id)
        effective = cls._datetime(
            command.get("effective_time"),
            "effective_time",
            required=status in {"FINAL", "AMENDED", "CORRECTED", "APPENDED"},
        )

        with transaction.atomic():
            report = cls._clinical_record(
                ClinicalDiagnosticReport,
                cls._resource_id(command),
                tenant_id,
                "DiagnosticReport",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(report, patient)
            if report:
                cls._transition(report.status, status, cls.REPORT_TRANSITIONS, "diagnostic report")
            else:
                report = ClinicalDiagnosticReport(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            report.encounter = encounter
            report.status = status
            report.category = command.get("category") or None
            report.code = code
            report.system = command.get("system") or None
            report.display = command.get("display") or None
            report.effective_time = effective
            report.conclusion = command.get("conclusion") or None
            cls._save(report)
            if "observations" in command:
                report.observations.set(
                    cls._observations(command.get("observations"), tenant_id, patient.id)
                )
            return report

    @classmethod
    def process_document_reference(cls, command: dict, tenant_id: str):
        tenant_id = cls._require_tenant_id(tenant_id)
        patient = cls._patient_reference(command.get("patient_id"), tenant_id)
        status = cls._choice(ClinicalDocument, "status", command.get("status"), "document status")
        object_url = cls._required_text(command, "object_url", "Document URL")
        if urlparse(object_url).scheme.lower() not in {"https", "s3"}:
            raise FHIRBusinessRuleError(
                "Clinical documents require an HTTPS or S3 object URL.",
                code="business-rule",
            )
        content_type = cls._required_text(command, "content_type", "Document content type")
        if "/" not in content_type:
            raise FHIRValidationError("Document content type must be a MIME type.", expression="content_type")
        size_bytes = command.get("size_bytes")
        if size_bytes is not None:
            try:
                size_bytes = int(size_bytes)
            except (TypeError, ValueError) as exc:
                raise FHIRValidationError("Document size must be an integer.", expression="size_bytes") from exc
            if size_bytes < 0:
                raise FHIRBusinessRuleError("Document size cannot be negative.", code="business-rule")
        hash_sha256 = str(command.get("hash_sha256") or "").strip().lower() or None
        if hash_sha256 and not re.fullmatch(r"[0-9a-f]{64}", hash_sha256):
            raise FHIRValidationError(
                "Document hash must be a 64-character SHA-256 hex digest.",
                expression="hash_sha256",
            )
        author = cls._owned_reference(
            Practitioner,
            command.get("author_id"),
            tenant_id,
            "Practitioner",
        )
        encounter = cls._encounter(command.get("encounter_id"), tenant_id, patient.id)

        with transaction.atomic():
            document = cls._clinical_record(
                ClinicalDocument,
                cls._resource_id(command),
                tenant_id,
                "DocumentReference",
                command.get("_operation"),
            )
            cls._assert_patient_immutable(document, patient)
            if document:
                cls._transition(document.status, status, cls.DOCUMENT_TRANSITIONS, "document")
            else:
                document = ClinicalDocument(
                    id=cls._resource_id(command) or uuid.uuid4(),
                    tenant_id=tenant_id,
                    patient=patient,
                )
            document.status = status
            document.doc_type = command.get("doc_type") or None
            document.category = command.get("category") or None
            document.author = author
            document.encounter = encounter
            document.object_url = object_url
            document.content_type = content_type
            document.size_bytes = size_bytes
            document.hash_sha256 = hash_sha256
            return cls._save(document)
