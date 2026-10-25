import base64
import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.fhir.converters.patient import PatientConverter
from apps.fhir.exceptions import FHIRReferenceResolutionError
from apps.fhir.kenya_hie import SYSTEM_CLIENT_REGISTRY_ID, extract_client_registry_id
from apps.fhir.services.reference_resolver import FHIRReferenceResolver
from apps.fhir.services.resource_lookup import PatientLookupService
from apps.identity.models import User
from apps.patients.identifier_crypto import IdentifierProtectionError, validate_identifier_keyrings
from apps.patients.identifier_crypto import PatientIdentifierProtector as protector
from apps.patients.models import Patient, PatientIdentifier
from apps.patients.services import PatientGovernanceService
from apps.tenancy.models import Tenant


def key(byte):
    return base64.urlsafe_b64encode(byte * 32).decode()


@pytest.fixture
def keys(settings):
    settings.DAWATRACE_PATIENT_IDENTIFIER_KEYS = {"id-old": key(b"a"), "id-new": key(b"b")}
    settings.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID = "id-old"
    settings.DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS = {"lookup-old": key(b"c"), "lookup-new": key(b"d")}
    settings.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID = "lookup-old"
    settings.DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS = []
    return settings


def test_new_protection_and_lookup_are_independent_of_django_secret(keys):
    tenant = uuid.uuid4()
    protected = protector.protect(tenant_id=tenant, value=" id 1234 ")
    digest = protector.digest(tenant_id=tenant, identifier_type="NATIONAL_ID", value="ID1234")
    assert protected.startswith("ttid1:id-old:")
    assert "ID1234" not in protected
    keys.SECRET_KEY = "completely-replaced-service-secret"
    assert protector.reveal(tenant_id=tenant, protected_value=protected) == "id 1234"
    assert protector.digest(tenant_id=tenant, identifier_type="NATIONAL_ID", value="id 1234") == digest
    with pytest.raises(ValidationError):
        protector.reveal(tenant_id=uuid.uuid4(), protected_value=protected)
    with pytest.raises(ValidationError):
        protector.reveal(tenant_id=tenant, protected_value=protected[:-8] + "tampered")
    with pytest.raises(ValidationError, match="255"):
        protector.protect(tenant_id=tenant, value="X" * 256)


def test_encryption_rotation_retains_old_reads_and_requires_old_key(keys):
    tenant = uuid.uuid4()
    old = protector.protect(tenant_id=tenant, value="ID1234")
    keys.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID = "id-new"
    new = protector.protect(tenant_id=tenant, value="ID1234")
    assert new.startswith("ttid1:id-new:")
    assert protector.reveal(tenant_id=tenant, protected_value=old) == "ID1234"
    keys.DAWATRACE_PATIENT_IDENTIFIER_KEYS = {"id-new": key(b"b")}
    with pytest.raises(ValidationError):
        protector.reveal(tenant_id=tenant, protected_value=old)
    assert protector.reveal(tenant_id=tenant, protected_value=new) == "ID1234"


@pytest.mark.parametrize("encryption,lookup,active,legacy", [
    ({}, {"lookup": key(b"l")}, "id", []),
    ({"id": "bad"}, {"lookup": key(b"l")}, "id", []),
    ({"id:unsafe": key(b"i")}, {"lookup": key(b"l")}, "id:unsafe", []),
    ({"id": key(b"i")}, {"lookup": key(b"i")}, "id", []),
    ({"id": key(b"i")}, {"lookup": key(b"l")}, "missing", []),
    ({"id": key(b"i")}, {"lookup": key(b"l")}, "id", "not-list"),
])
def test_keyring_configuration_fails_closed(encryption, lookup, active, legacy):
    with pytest.raises(IdentifierProtectionError):
        validate_identifier_keyrings(encryption, active, lookup, "lookup", legacy)


@pytest.mark.parametrize("mode", ["missing", "reused", "valid"])
def test_production_startup_requires_independent_identifier_keys(mode):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "dawatrace.settings.production",
        "DAWATRACE_ENV": "production",
        "DAWATRACE_SECRET_KEY": "synthetic-production-settings-secret",
        "DAWATRACE_OBJECT_SIGNING_KEY": "synthetic-signing-key",
        "DAWATRACE_ALLOWED_HOSTS": "example.test",
        "DAWATRACE_CSRF_TRUSTED_ORIGINS": "https://example.test",
        "DAWATRACE_FHIR_PUBLIC_BASE_URL": "https://example.test/fhir/",
        "DAWATRACE_DATABASE_URL": "sqlite:///:memory:",
        "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS": json.dumps({"doc": key(b"o")}),
        "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID": "doc",
        "DAWATRACE_PATIENT_IDENTIFIER_KEYS": json.dumps({"id": key(b"i")} if mode != "missing" else {}),
        "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID": "id",
        "DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS": json.dumps({"lookup": key(b"i" if mode == "reused" else b"l")}),
        "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID": "lookup",
    }
    result = subprocess.run([sys.executable, "-c", "import django; django.setup()"],
                            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, check=False)
    if mode == "valid":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "Valid independent patient identifier encryption and lookup keyrings" in result.stderr
        assert key(b"i") not in result.stderr


def legacy_row(tenant, patient, *, value, secret=None, normalized_override=None):
    normalized = normalized_override or protector.normalize(value)
    protected = ""
    digest = ""
    if secret:
        oldkey = base64.urlsafe_b64encode(hashlib.sha256(f"{secret}:patient-identifier:{tenant.pk}".encode()).digest())
        protected = Fernet(oldkey).encrypt(normalized.encode()).decode()
        digest = hmac.new(f"{secret}:{tenant.pk}".encode(), f"OTHER:{normalized}".encode(), hashlib.sha256).hexdigest()
    # Raw insert deliberately simulates an existing pre-migration database row.
    row = PatientIdentifier(tenant=tenant, patient=patient, system=SYSTEM_CLIENT_REGISTRY_ID, identifier_type="OTHER",
                            value="" if secret else value, protected_value=protected, value_hash=digest,
                            last_four=normalized[-4:], verification_status="VERIFIED")
    PatientIdentifier.all_objects.bulk_create([row])
    return row


@pytest.fixture
def records(db):
    tenant = Tenant.objects.create(name="Synthetic identity tenant", slug="synthetic-identity")
    patient = Patient.all_objects.create(tenant=tenant, internal_reference_id="SYNTH-P1")
    return tenant, patient


@pytest.mark.django_db
def test_direct_and_fhir_identifier_writes_are_protected_and_searchable(keys, records):
    tenant, patient = records
    row = PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system=SYSTEM_CLIENT_REGISTRY_ID,
                                              value="cr-1234", verification_status="VERIFIED")
    row.refresh_from_db()
    assert row.value == "" and row.lookup_key_id == "lookup-old"
    assert row.value_for_exchange() == "cr-1234"
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "cr-1234", tenant.pk) == patient
    assert PatientLookupService.search({"identifier": f"{SYSTEM_CLIENT_REGISTRY_ID}|cr-1234"}, tenant.pk) == [patient]
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "cr-1234", uuid.uuid4()) is None
    rendered = PatientConverter().to_fhir(patient, {"tenant_id": tenant.pk})
    assert rendered.fhir_resource
    assert any(i.value == "cr-1234" for i in rendered.fhir_resource.identifier)
    assert extract_client_registry_id(patient) == "cr-1234"
    assert PatientConverter().to_fhir(patient, {"tenant_id": uuid.uuid4()}).fhir_resource is None
    created = PatientLookupService.process_domain_command({"internal_reference_id": "SYNTH-P2", "identifiers": [
        {"system": "urn:synthetic:mrn", "value": "MRN-5678"}]}, {"tenant_id": tenant.pk})
    assert not PatientIdentifier.all_objects.get(patient=created).value
    assert PatientLookupService.get_by_identifier("urn:synthetic:mrn", "MRN-5678", tenant.pk) == created


@pytest.mark.django_db
def test_governance_intake_preserves_external_identifier_case(keys, records):
    tenant, patient = records
    actor = User.objects.create_user(username="synthetic-identity-author", tenant=tenant)
    actor.has_capability = lambda *args, **kwargs: True
    row = PatientGovernanceService.add_identifier(patient=patient, actor=actor, identifier_type="OTHER",
                                                  system=SYSTEM_CLIENT_REGISTRY_ID, value="Cr-Mixed 123")
    assert row.value == ""
    assert PatientGovernanceService.reveal_identifier(identifier=row, actor=actor, reason="Synthetic readback") == "Cr-Mixed 123"
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "Cr-Mixed 123", tenant.pk) == patient
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "CR-MIXED123", tenant.pk) is None
    assert "Cr-Mixed 123" not in json.dumps(list(AuditEvent.all_objects.values("object_id", "metadata")))


@pytest.mark.django_db
def test_duplicate_detection_survives_lookup_key_rotation_and_missing_key_blocks(keys, records):
    tenant, patient = records
    row = PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="urn:synthetic", identifier_type="NATIONAL_ID", value="ID-1234")
    keys.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID = "lookup-new"
    assert PatientLookupService.get_by_identifier("urn:synthetic", "ID-1234", tenant.pk) == patient
    with transaction.atomic(), pytest.raises(ValidationError, match="already registered"):
        PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="urn:different", identifier_type="NATIONAL_ID", value="id-1234")
    keys.DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS = {"lookup-new": key(b"d")}
    with pytest.raises(ValidationError, match="Historical"):
        PatientLookupService.get_by_identifier("urn:synthetic", "ID-1234", tenant.pk)
    with transaction.atomic(), pytest.raises(ValidationError, match="Historical"):
        PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="urn:synthetic", value="OTHER-9999")
    row.refresh_from_db()
    assert row.lookup_key_id == "lookup-old"


@pytest.mark.django_db
def test_legacy_reads_require_explicit_historical_secret_and_rotate_atomically(keys, records):
    tenant, patient = records
    old_secret = "explicit-old-test-service-secret"
    row = legacy_row(tenant, patient, value="CR-1234", secret=old_secret)
    with pytest.raises(ValidationError):
        protector.reveal(tenant_id=tenant.pk, protected_value=row.protected_value)
    keys.DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS = [old_secret]
    keys.SECRET_KEY = "different-current-django-secret"
    assert row.value_for_exchange() == "CR-1234"
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "CR-1234", tenant.pk) == patient
    before = PatientIdentifier.all_objects.get(pk=row.pk).protected_value
    output = io.StringIO()
    call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), stdout=output)
    row.refresh_from_db()
    assert row.protected_value == before and "No records changed" in output.getvalue()
    keys.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID = "id-new"
    keys.DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID = "lookup-new"
    call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), apply=True, stdout=output)
    row.refresh_from_db()
    assert row.protected_value.startswith("ttid1:id-new:") and row.lookup_key_id == "lookup-new" and row.value == ""
    keys.DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS = []
    assert row.value_for_exchange() == "CR-1234"
    assert PatientLookupService.get_by_identifier(SYSTEM_CLIENT_REGISTRY_ID, "CR-1234", tenant.pk) == patient
    call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), apply=True, stdout=output)
    assert AuditEvent.all_objects.filter(action="PATIENT_IDENTIFIER_KEYS_ROTATED").count() == 1
    assert "CR-1234" not in output.getvalue() and old_secret not in output.getvalue()
    assert "CR-1234" not in json.dumps(list(AuditEvent.all_objects.values("metadata")))


@pytest.mark.django_db
def test_rotation_preflight_refuses_missing_keys_tamper_and_logical_duplicates(keys, records):
    tenant, patient = records
    row = legacy_row(tenant, patient, value="CR-1234", secret="old-test-secret")
    output = io.StringIO()
    with pytest.raises(CommandError, match="Preflight refused"):
        call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), apply=True, stdout=output)
    row.refresh_from_db()
    assert not row.lookup_key_id
    PatientIdentifier.all_objects.filter(pk=row.pk).delete()
    a = legacy_row(tenant, patient, value=" CR1234 ")
    b = legacy_row(tenant, patient, value="CR1234")
    with pytest.raises(CommandError, match="duplicate logical"):
        call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), apply=True, stdout=output)
    assert PatientIdentifier.all_objects.get(pk=a.pk).value == " CR1234 "
    assert PatientIdentifier.all_objects.get(pk=b.pk).value == "CR1234"
    assert not AuditEvent.all_objects.filter(action="PATIENT_IDENTIFIER_KEYS_ROTATED").exists()


@pytest.mark.django_db
def test_rotation_refuses_corrupt_cross_tenant_relationship(keys, records):
    tenant, patient = records
    foreign = Tenant.objects.create(name="Synthetic foreign tenant", slug="synthetic-foreign")
    row = legacy_row(foreign, patient, value="SYNTH-CROSS-1234")
    with pytest.raises(CommandError, match="Preflight refused"):
        call_command("rotate_patient_identifier_keys", tenant_id=str(foreign.pk), apply=True, stdout=io.StringIO())
    row.refresh_from_db()
    assert row.value == "SYNTH-CROSS-1234" and not row.protected_value


@pytest.mark.django_db
def test_crypto_metadata_cannot_be_forged_on_normal_writes(keys, records):
    tenant, patient = records
    row = PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="urn:synthetic", value="ID-1234")
    row.value_hash = "a" * 64
    with transaction.atomic(), pytest.raises(ValidationError, match="integrity"):
        row.save()
    row.refresh_from_db()
    row.last_four = "0000"
    with transaction.atomic(), pytest.raises(ValidationError, match="suffix"):
        row.save()


@pytest.mark.django_db
def test_fhir_identifier_namespace_and_case_survive_encryption(keys, records):
    tenant, patient = records
    other = Patient.all_objects.create(tenant=tenant, internal_reference_id="SYNTH-OTHER")
    PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="urn:hospital:a", value="Mrn-Ab12")
    PatientIdentifier.all_objects.create(tenant=tenant, patient=other, system="urn:hospital:b", value="Mrn-Ab12")
    assert PatientLookupService.get_by_identifier("urn:hospital:a", "Mrn-Ab12", tenant.pk) == patient
    assert PatientLookupService.get_by_identifier("urn:hospital:b", "Mrn-Ab12", tenant.pk) == other
    assert PatientLookupService.get_by_identifier("urn:hospital:a", "MRN-AB12", tenant.pk) is None
    assert PatientLookupService.get_by_identifier("urn:unknown", patient.internal_reference_id, tenant.pk) is None
    assert PatientLookupService.search({"identifier": f"urn:unknown|{patient.internal_reference_id}"}, tenant.pk) == []
    with pytest.raises(ValidationError, match="ambiguous"):
        PatientLookupService.get_by_identifier("", "Mrn-Ab12", tenant.pk)
    with pytest.raises(FHIRReferenceResolutionError):
        FHIRReferenceResolver.resolve_identifier_for_tenant(tenant.pk, "Patient", {"value": "Mrn-Ab12"})
    FHIRReferenceResolver.resolve_identifier_for_tenant(tenant.pk, "Patient", {"system": "urn:hospital:a", "value": "Mrn-Ab12"})
    audits = AuditEvent.all_objects.filter(action="FHIR_REFERENCE_RESOLVE")
    assert audits.count() == 2
    assert "Mrn-Ab12" not in json.dumps(list(audits.values("object_id", "metadata")))


@pytest.mark.django_db
def test_rotation_rolls_back_all_rows_when_audit_write_fails(keys, records, monkeypatch):
    tenant, patient = records
    a = legacy_row(tenant, patient, value="CR-1234")
    b = legacy_row(tenant, patient, value="CR-5678")
    def fail_audit(**kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr("apps.patients.management.commands.rotate_patient_identifier_keys.log_audit", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        call_command("rotate_patient_identifier_keys", tenant_id=str(tenant.pk), apply=True, stdout=io.StringIO())
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.value == "CR-1234" and b.value == "CR-5678"
    assert not a.lookup_key_id and not b.lookup_key_id


@pytest.mark.django_db(transaction=True)
def test_concurrent_identity_writers_share_tenant_lock(keys):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks.")
    tenant = Tenant.objects.create(name="Concurrent identity", slug="concurrent-identity")
    barrier = Barrier(2)
    def create(index):
        close_old_connections()
        try:
            with transaction.atomic():
                # Each transaction already holds a tenant FK key-share lock.
                # Identity serialization must not require upgrading that lock
                # to FOR UPDATE, which can deadlock concurrent patient intake.
                patient = Patient.all_objects.create(tenant_id=tenant.pk, internal_reference_id=f"SYNTH-CONCURRENT-{index}")
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                barrier.wait(timeout=10)
                PatientIdentifier.all_objects.create(tenant_id=tenant.pk, patient_id=patient.pk, system="urn:concurrent", value="SAME-1234")
                return "created"
        except ValidationError:
            return "rejected"
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create, range(2)))
    assert sorted(results) == ["created", "rejected"]
    assert PatientIdentifier.all_objects.filter(tenant=tenant).count() == 1
    assert Patient.all_objects.filter(tenant=tenant).count() == 1
