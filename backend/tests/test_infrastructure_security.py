from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.crosswalks.models import LegacyIdentifierCrosswalk, LegacySystem
from apps.crosswalks.services import CrosswalkService
from apps.documents.models import DocumentAccessEvent
from apps.documents.storage import LocalClinicalObjectStorage
from apps.identity.models import ExternalIdentityMapping, Role, User, UserRole
from apps.notifications.models import NotificationOutbox
from apps.notifications.tasks import process_notification
from apps.prescription.management.lookup_safety import find_unscoped_uuid_lookups
from apps.prescription.management.manager_safety import audit_tenant_managers
from apps.prescription.models import IntegrationOutbox, ProviderConfiguration
from apps.prescription.providers.base import AdapterFactory, ProviderUnavailable
from apps.prescription.services.observability import ObservabilityService
from apps.prescription.services.queue_processor import IntegrationQueueProcessor
from apps.workflows.service import emit_event
from apps.workflows.tasks import process_domain_event

pytestmark = [pytest.mark.django_db, pytest.mark.infrastructure, pytest.mark.security]


@pytest.fixture
def legacy_system():
    return LegacySystem.objects.create(
        code="MERCATO_LEGACY",
        name="Mercato-OS legacy source",
        source_environment="migration-test",
        metadata={"connection": "none"},
    )


@pytest.fixture
def crosswalk(tenant_a, legacy_system):
    return LegacyIdentifierCrosswalk.all_objects.create(
        tenant=tenant_a,
        source_system=legacy_system,
        source_entity_type="pharmacy.Patient",
        source_identifier="legacy-patient-001",
        target_entity_type="patients.Patient",
        target_uuid=uuid.uuid4(),
        source_hash="a" * 64,
        migration_batch="phase2-test",
        immutable_metadata={"source_table": "pharmacy_patient"},
    )


def _tenant_user(tenant, username, capabilities):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password-strong",
        tenant=tenant,
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code=f"ROLE_{username.upper()}",
        name=f"Role for {username}",
        capabilities=capabilities,
    )
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


def _store_document(settings, tmp_path, clinical_setup, clinical_user, content=b"%PDF-1.4\nDawaTrace"):
    settings.MEDIA_ROOT = tmp_path

    class CleanScanner:
        def scan(self, supplied):
            assert supplied == content
            return "CLEAN"

    return LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="clinical-note.pdf",
        content_type="application/pdf",
        content=content,
        actor=clinical_user,
        scanner=CleanScanner(),
    )


def test_document_upload_fails_closed_without_malware_scanner_in_production(
    settings, tmp_path, clinical_setup, clinical_user
):
    settings.DAWATRACE_ENV = "production"
    settings.MEDIA_ROOT = tmp_path

    with pytest.raises(ValidationError, match="clean malware scan"):
        LocalClinicalObjectStorage.store(
            tenant_id=clinical_setup["tenant"].id,
            patient=clinical_setup["patient"],
            original_name="clinical-note.pdf",
            content_type="application/pdf",
            content=b"%PDF-1.4\nDawaTrace",
            actor=clinical_user,
        )

    assert not DocumentAccessEvent.all_objects.filter(tenant=clinical_setup["tenant"]).exists()


def test_crosswalk_duplicate_is_prevented(crosswalk):
    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyIdentifierCrosswalk.all_objects.create(
            tenant=crosswalk.tenant,
            source_system=crosswalk.source_system,
            source_entity_type=crosswalk.source_entity_type,
            source_identifier=crosswalk.source_identifier,
            target_entity_type="patients.Patient",
            target_uuid=uuid.uuid4(),
            migration_batch="retry",
        )


def test_crosswalk_is_immutable_and_not_application_deletable(crosswalk):
    crosswalk.target_uuid = uuid.uuid4()
    with pytest.raises(ValidationError, match="immutable"):
        crosswalk.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        crosswalk.delete()


def test_crosswalk_resolution_is_idempotent_and_tenant_scoped(crosswalk, tenant_b):
    kwargs = {
        "source_system_code": crosswalk.source_system.code,
        "source_entity_type": crosswalk.source_entity_type,
        "source_identifier": crosswalk.source_identifier,
    }
    first = CrosswalkService.resolve(tenant_id=crosswalk.tenant_id, **kwargs)
    second = CrosswalkService.resolve(tenant_id=crosswalk.tenant_id, **kwargs)
    assert first.id == second.id == crosswalk.id
    assert CrosswalkService.resolve(tenant_id=tenant_b.id, **kwargs) is None


def test_crosswalk_supports_auditable_missing_target(tenant_a, legacy_system):
    row = LegacyIdentifierCrosswalk.all_objects.create(
        tenant=tenant_a,
        source_system=legacy_system,
        source_entity_type="pharmacy.Patient",
        source_identifier="unresolved-patient",
        target_entity_type="patients.Patient",
        target_uuid=None,
        migration_batch="reconciliation-test",
        immutable_metadata={"status": "UNRESOLVED"},
    )
    resolved = CrosswalkService.resolve(
        tenant_id=tenant_a.id,
        source_system_code=legacy_system.code,
        source_entity_type=row.source_entity_type,
        source_identifier=row.source_identifier,
    )
    assert resolved.target_uuid is None
    assert resolved.immutable_metadata["status"] == "UNRESOLVED"


def test_crosswalk_target_is_uuid_not_live_foreign_key():
    field = LegacyIdentifierCrosswalk._meta.get_field("target_uuid")
    assert not field.many_to_one
    assert field.remote_field is None


def test_external_identity_mapping_rejects_cross_tenant_user(tenant_a, tenant_b):
    user_b = _tenant_user(tenant_b, "identity-b", ["patients.read"])
    with pytest.raises(ValidationError):
        ExternalIdentityMapping.all_objects.create(
            tenant=tenant_a,
            user=user_b,
            issuer="https://identity.example.test",
            subject="cross-tenant-subject",
        )


def test_external_identity_subject_is_unique_per_tenant(clinical_user):
    ExternalIdentityMapping.all_objects.create(
        tenant_id=clinical_user.tenant_id,
        user=clinical_user,
        issuer="https://identity.example.test",
        subject="clinical-user",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ExternalIdentityMapping.all_objects.create(
            tenant_id=clinical_user.tenant_id,
            user=clinical_user,
            issuer="https://identity.example.test",
            subject="clinical-user",
        )


def test_emit_event_requires_explicit_tenant(clinical_setup):
    with pytest.raises(ValueError, match="explicit tenant"):
        emit_event(
            tenant_id=None,
            aggregate_type="Prescription",
            aggregate_id=clinical_setup["patient"].id,
            event_type="TEST",
            payload={},
        )


def test_domain_event_job_processes_only_in_supplied_tenant(clinical_setup):
    event = emit_event(
        tenant_id=clinical_setup["tenant"].id,
        aggregate_type="Patient",
        aggregate_id=clinical_setup["patient"].id,
        event_type="PATIENT_TESTED",
        payload={"contains_phi": False},
    )
    assert process_domain_event.run(str(event.id), str(clinical_setup["tenant"].id)) == str(event.id)
    event.refresh_from_db()
    assert event.status == "PROCESSED"
    assert event.attempts == 1
    assert event.processed_at is not None


def test_domain_event_job_denies_cross_tenant_and_audits_attempt(clinical_setup, tenant_b):
    event = emit_event(
        tenant_id=clinical_setup["tenant"].id,
        aggregate_type="Patient",
        aggregate_id=clinical_setup["patient"].id,
        event_type="PATIENT_TESTED",
        payload={},
    )
    with pytest.raises(ValueError, match="unavailable"):
        process_domain_event.run(str(event.id), str(tenant_b.id))
    event.refresh_from_db()
    assert event.status == "PENDING"
    audit = AuditEvent.all_objects.get(tenant=tenant_b, object_id=str(event.id))
    assert audit.action == "BACKGROUND_JOB_DENIED"
    assert audit.metadata["reason"] == "EVENT_OUTSIDE_TENANT_OR_MISSING"


def test_notification_job_has_no_external_transport_and_is_tenant_safe(tenant_a):
    notification = NotificationOutbox.all_objects.create(
        tenant=tenant_a,
        channel="EMAIL",
        recipient="patient@example.test",
        template_code="PRESCRIPTION_READY",
        payload={"reference": "safe-reference"},
        idempotency_key="notification-1",
    )
    assert process_notification.run(str(notification.id), str(tenant_a.id)) == str(notification.id)
    notification.refresh_from_db()
    assert notification.status == "READY"


def test_notification_job_denies_cross_tenant_and_audits_attempt(tenant_a, tenant_b):
    notification = NotificationOutbox.all_objects.create(
        tenant=tenant_a,
        channel="SMS",
        recipient="redacted",
        template_code="TEST",
        idempotency_key="notification-cross-tenant",
    )
    with pytest.raises(ValueError, match="unavailable"):
        process_notification.run(str(notification.id), str(tenant_b.id))
    notification.refresh_from_db()
    assert notification.status == "PENDING"
    assert AuditEvent.all_objects.filter(
        tenant=tenant_b,
        model_name="NotificationOutbox",
        object_id=str(notification.id),
        outcome="FAILED",
    ).exists()


@pytest.mark.parametrize("provider_code", ["DHA", "SHA", "HOSPITAL_EMR"])
def test_unconfigured_provider_adapters_fail_closed(provider_code):
    adapter = AdapterFactory.get_adapter(provider_code)
    assert adapter.check_health() is False
    assert adapter.verify_prescription("test")["is_valid"] is False
    assert adapter.validate_practitioner("test") is False
    with pytest.raises(ProviderUnavailable):
        adapter.submit_dispense({"test": True})


def test_integration_queue_requires_explicit_tenant():
    with pytest.raises(ValueError, match="explicit tenant"):
        IntegrationQueueProcessor.process_pending_messages(tenant_id=None)


def test_integration_queue_and_health_are_tenant_scoped_and_fail_closed(tenant_a, tenant_b):
    ProviderConfiguration.all_objects.create(
        tenant=tenant_a,
        provider_code="DHA",
        base_url="https://provider.invalid.example",
        auth_type="NONE",
    )
    message = IntegrationOutbox.all_objects.create(
        tenant=tenant_a,
        provider_code="DHA",
        event_type="SUBMIT_DISPENSE",
        payload={"reference": "test-only"},
        correlation_id="provider-test-1",
        idempotency_key="provider-test-1",
    )
    assert IntegrationQueueProcessor.process_pending_messages(tenant_id=tenant_b.id) == 0
    message.refresh_from_db()
    assert message.status == "PENDING"
    assert IntegrationQueueProcessor.process_pending_messages(tenant_id=tenant_a.id) == 1
    message.refresh_from_db()
    assert message.status == "RETRYING"
    assert "not configured" in message.last_error
    assert ObservabilityService.get_provider_health(tenant_id=tenant_b.id) == {}
    health = ObservabilityService.get_provider_health(tenant_id=tenant_a.id)["DHA"]
    assert health["configured"] is True
    assert health["adapter_reachable"] is False


def test_document_store_and_authorized_read_are_hash_verified(
    settings, tmp_path, clinical_setup, clinical_user
):
    content = b"%PDF-1.4\nDawaTrace"
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user, content)
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    assert LocalClinicalObjectStorage.read(
        token=token,
        actor=clinical_user,
        tenant_id=str(clinical_setup["tenant"].id),
    ) == content
    document.refresh_from_db()
    assert document.object_key.startswith(f"tenant/{clinical_setup['tenant'].id}/")
    assert document.malware_scan_status == "CLEAN"
    assert DocumentAccessEvent.all_objects.filter(document=document, outcome="SUCCESS").count() == 2


def test_document_signed_token_requires_capability(settings, tmp_path, clinical_setup, clinical_user, cashier_user):
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user)
    with pytest.raises(PermissionDenied):
        LocalClinicalObjectStorage.signed_token(document=document, actor=cashier_user)


def test_document_read_denies_cross_tenant(settings, tmp_path, clinical_setup, clinical_user, tenant_b):
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user)
    clinical_user.is_platform_admin = True
    clinical_user.save(update_fields=["is_platform_admin"])
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    with pytest.raises(PermissionDenied):
        LocalClinicalObjectStorage.read(
            token=token,
            actor=clinical_user,
            tenant_id=str(tenant_b.id),
        )


def test_document_read_reports_missing_database_record(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    token = signing.dumps(
        {
            "document_id": str(uuid.uuid4()),
            "tenant_id": str(clinical_setup["tenant"].id),
            "actor_id": str(clinical_user.id),
        },
        salt="dawatrace.document",
    )
    with pytest.raises(FileNotFoundError, match="unavailable"):
        LocalClinicalObjectStorage.read(
            token=token,
            actor=clinical_user,
            tenant_id=str(clinical_setup["tenant"].id),
        )


def test_document_read_reports_missing_object(settings, tmp_path, clinical_setup, clinical_user):
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user)
    LocalClinicalObjectStorage._path(document.object_key).unlink()
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    with pytest.raises(FileNotFoundError, match="missing"):
        LocalClinicalObjectStorage.read(
            token=token,
            actor=clinical_user,
            tenant_id=str(clinical_setup["tenant"].id),
        )


def test_document_hash_mismatch_is_blocked_and_audited(settings, tmp_path, clinical_setup, clinical_user):
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user)
    LocalClinicalObjectStorage._path(document.object_key).write_bytes(b"tampered")
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    with pytest.raises(ValidationError, match="integrity"):
        LocalClinicalObjectStorage.read(
            token=token,
            actor=clinical_user,
            tenant_id=str(clinical_setup["tenant"].id),
        )
    assert DocumentAccessEvent.all_objects.filter(document=document, outcome="HASH_MISMATCH").exists()


@pytest.mark.parametrize(
    ("name", "content_type"),
    [("note.exe", "application/x-msdownload"), ("note.jpg", "application/pdf")],
)
def test_document_upload_rejects_invalid_content_type_or_extension(
    settings, tmp_path, clinical_setup, clinical_user, name, content_type
):
    settings.MEDIA_ROOT = tmp_path
    with pytest.raises(ValidationError):
        LocalClinicalObjectStorage.store(
            tenant_id=clinical_setup["tenant"].id,
            patient=clinical_setup["patient"],
            original_name=name,
            content_type=content_type,
            content=b"unsafe",
            actor=clinical_user,
        )


def test_document_upload_enforces_size_limit(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_DOCUMENT_MAX_BYTES = 4
    with pytest.raises(ValidationError, match="size limit"):
        LocalClinicalObjectStorage.store(
            tenant_id=clinical_setup["tenant"].id,
            patient=clinical_setup["patient"],
            original_name="note.txt",
            content_type="text/plain",
            content=b"12345",
            actor=clinical_user,
        )


def test_document_api_authorizes_download(settings, tmp_path, clinical_setup, clinical_user):
    document = _store_document(settings, tmp_path, clinical_setup, clinical_user)
    client = APIClient()
    client.force_authenticate(clinical_user)
    headers = {"HTTP_X_TENANT_ID": str(clinical_setup["tenant"].id)}
    token_response = client.post(f"/api/documents/{document.id}/signed-token/", {}, format="json", **headers)
    assert token_response.status_code == 200
    download = client.post(
        "/api/documents/download/",
        {"token": token_response.data["token"]},
        format="json",
        **headers,
    )
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4\nDawaTrace"


def test_document_api_denies_user_without_capability(clinical_setup, cashier_user):
    client = APIClient()
    client.force_authenticate(cashier_user)
    response = client.get(
        "/api/documents/", HTTP_X_TENANT_ID=str(clinical_setup["tenant"].id)
    )
    assert response.status_code == 403


def test_unsafe_uuid_lookup_audit_has_no_unreviewed_findings():
    findings = find_unscoped_uuid_lookups(Path(__file__).resolve().parents[1] / "apps")
    assert findings == []


def test_tenant_model_manager_audit_has_no_unreviewed_findings():
    result = audit_tenant_managers()
    assert result["model_count"] >= 50
    assert result["finding_count"] == 0
    assert result["approved_exception_count"] == 1


def test_health_endpoint_reports_independent_product_metadata():
    response = Client().get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "product": "DawaTrace",
        "vendor": "Esenai Group Ltd",
        "fhir_version": "4.0.1",
    }


def test_administrative_shell_is_authenticated_and_tenant_scoped(clinical_setup, clinical_user):
    anonymous = Client().get("/admin-shell/")
    assert anonymous.status_code == 302
    client = Client()
    client.force_login(clinical_user)
    response = client.get("/admin-shell/")
    assert response.status_code == 200
    assert b"DawaTrace" in response.content
    assert b"Patients" in response.content
    assert b">1<" in response.content
