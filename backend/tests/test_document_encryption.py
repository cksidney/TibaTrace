from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.documents.encryption import (
    DocumentEncryptionError,
    decrypt_document_bytes,
    encrypt_document_bytes,
    validate_document_keyring,
)
from apps.documents.models import DocumentAccessEvent
from apps.documents.storage import LocalClinicalObjectStorage


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


class _CleanScanner:
    def scan(self, content: bytes) -> str:
        return "CLEAN"


@pytest.mark.django_db
def test_upload_cannot_claim_generated_record_exemption(settings, tmp_path, clinical_setup, clinical_user):
    settings.DAWATRACE_ENV = "production"
    settings.MEDIA_ROOT = tmp_path
    class ForgedScanner:
        def scan(self, content):
            return "NOT_APPLICABLE"
    with pytest.raises(ValidationError, match="clean malware scan"):
        LocalClinicalObjectStorage.store(
            tenant_id=clinical_setup["tenant"].pk, patient=clinical_setup["patient"],
            original_name="uploaded.txt", content_type="text/plain", content=b"untrusted bytes",
            actor=clinical_user, scanner=ForgedScanner(),
        )


@pytest.mark.django_db
def test_generated_record_only_accepts_structured_text(settings, clinical_setup, clinical_user):
    with pytest.raises(ValidationError, match="structured JSON text"):
        LocalClinicalObjectStorage.store_generated_json(
            tenant_id=clinical_setup["tenant"].pk, patient=clinical_setup["patient"],
            original_name="source.pdf", payload=b"%PDF-1.4 untrusted file", actor=clinical_user,
        )


@pytest.mark.django_db
def test_reenabling_scanning_does_not_certify_old_objects_without_a_scan(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": _key()}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = False
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    command = dict(tenant_id=clinical_setup["tenant"].pk, patient=clinical_setup["patient"],
                   original_name="rx.txt", content_type="text/plain", content=b"original source", actor=clinical_user)
    document = LocalClinicalObjectStorage.store(**command)
    assert document.malware_scan_status == "NOT_SCANNED"
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = True
    document.refresh_from_db()
    assert document.malware_scan_status == "NOT_SCANNED"
    with pytest.raises(ValidationError, match="clean malware scan"):
        LocalClinicalObjectStorage.store(**command)
    document.refresh_from_db()
    assert document.malware_scan_status == "NOT_SCANNED"
    rescanned = LocalClinicalObjectStorage.store(**command, scanner=_CleanScanner())
    assert rescanned.pk == document.pk and rescanned.malware_scan_status == "CLEAN"
    assert rescanned.metadata["malware_scanning_performed"] is True
    assert rescanned.metadata["malware_scanning_policy"] == "REQUIRED"


def test_document_encryption_is_authenticated_and_bound_to_object_key():
    key = _key()
    payload = encrypt_document_bytes(
        b"sensitive clinical note", key_id="k1", key=key, associated_data="tenant/1/file.pdf"
    )

    plaintext, key_id = decrypt_document_bytes(payload, keyring={"k1": key}, associated_data="tenant/1/file.pdf")
    assert plaintext == b"sensitive clinical note"
    assert key_id == "k1"
    assert b"sensitive clinical note" not in payload
    with pytest.raises(DocumentEncryptionError, match="authenticated decryption"):
        decrypt_document_bytes(payload, keyring={"k1": key}, associated_data="tenant/2/file.pdf")


def test_document_encryption_supports_key_rotation_and_reads_legacy_bytes():
    old_key, new_key = _key(), _key()
    payload = encrypt_document_bytes(b"clinical attachment", key_id="old", key=old_key, associated_data="object-key")
    plaintext, key_id = decrypt_document_bytes(
        payload, keyring={"old": old_key, "new": new_key}, associated_data="object-key"
    )
    rotated = encrypt_document_bytes(plaintext, key_id="new", key=new_key, associated_data="object-key")
    assert decrypt_document_bytes(rotated, keyring={"old": old_key, "new": new_key}, associated_data="object-key") == (
        b"clinical attachment",
        "new",
    )
    assert decrypt_document_bytes(b"legacy plaintext", keyring={}, associated_data="object-key") == (
        b"legacy plaintext",
        None,
    )


def test_document_keyring_requires_active_valid_256_bit_key():
    with pytest.raises(DocumentEncryptionError, match="Active"):
        validate_document_keyring({"old": _key()}, "missing")
    with pytest.raises(DocumentEncryptionError, match="32 bytes"):
        validate_document_keyring({"active": "bad"}, "active")


def test_production_settings_require_and_accept_document_keyring():
    backend_root = Path(__file__).resolve().parents[1]
    base_env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "dawatrace.settings.production",
        "DAWATRACE_ENV": "production",
        "DAWATRACE_SECRET_KEY": "test-only-production-settings-secret",
        "DAWATRACE_OBJECT_SIGNING_KEY": "test-only-object-signing-key",
        "DAWATRACE_ALLOWED_HOSTS": "example.test",
        "DAWATRACE_CSRF_TRUSTED_ORIGINS": "https://example.test",
        "DAWATRACE_FHIR_PUBLIC_BASE_URL": "https://example.test/fhir/",
        "DAWATRACE_DATABASE_URL": "sqlite:///:memory:",
        "DAWATRACE_PATIENT_IDENTIFIER_KEYS": json.dumps({"id-test": base64.urlsafe_b64encode(b"I" * 32).decode()}),
        "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID": "id-test",
        "DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS": json.dumps({"lookup-test": base64.urlsafe_b64encode(b"J" * 32).decode()}),
        "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID": "lookup-test",
    }
    missing_keyring_env = base_env | {
        "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS": "{}",
        "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID": "",
    }
    missing_keyring = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=backend_root,
        env=missing_keyring_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_keyring.returncode != 0
    assert "active clinical-document encryption keyring is required" in missing_keyring.stderr

    mislabeled_environment = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=backend_root,
        env=base_env | {
            "DAWATRACE_ENV": "staging",
            "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS": "{}",
            "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID": "",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert mislabeled_environment.returncode != 0
    assert "active clinical-document encryption keyring is required" in mislabeled_environment.stderr

    valid_key = _key()
    valid_keyring_env = base_env | {
        "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS": json.dumps({"test-k1": valid_key}),
        "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID": "test-k1",
    }
    valid_keyring = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=backend_root,
        env=valid_keyring_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid_keyring.returncode == 0, valid_keyring.stderr


def test_production_upload_encrypts_and_reads_attachment(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "production"
    key = _key()
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": key}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    content = b"%PDF-1.4\nprivate clinical information"
    document = LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="record.pdf",
        content_type="application/pdf",
        content=content,
        actor=clinical_user,
        scanner=_CleanScanner(),
    )
    path = LocalClinicalObjectStorage._path(document.object_key)
    assert content not in path.read_bytes()
    assert document.metadata["at_rest_encryption"] == {"algorithm": "AES-256-GCM", "key_id": "k1", "version": 1}
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    assert (
        LocalClinicalObjectStorage.read(token=token, actor=clinical_user, tenant_id=str(clinical_setup["tenant"].id))
        == content
    )


def test_production_upload_fails_closed_without_encryption_key(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = ""
    with pytest.raises(ValidationError, match="encryption is not configured"):
        LocalClinicalObjectStorage.store(
            tenant_id=clinical_setup["tenant"].id,
            patient=clinical_setup["patient"],
            original_name="record.pdf",
            content_type="application/pdf",
            content=b"%PDF-1.4\nclinical information",
            actor=clinical_user,
            scanner=_CleanScanner(),
        )


def test_encrypted_object_tampering_is_denied_and_audited(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": _key()}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    document = LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="tampered.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nprivate clinical information",
        actor=clinical_user,
        scanner=_CleanScanner(),
    )
    path = LocalClinicalObjectStorage._path(document.object_key)
    tampered = bytearray(path.read_bytes())
    tampered[-1] ^= 1
    path.write_bytes(tampered)
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    with pytest.raises(ValidationError, match="decrypted safely"):
        LocalClinicalObjectStorage.read(token=token, actor=clinical_user, tenant_id=str(clinical_setup["tenant"].id))
    assert DocumentAccessEvent.all_objects.filter(document=document, outcome="DECRYPTION_FAILED").exists()


def test_encryption_migration_is_dry_run_then_atomically_applies(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "development"
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = ""
    content = b"%PDF-1.4\nlegacy clinical information"
    document = LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="legacy.pdf",
        content_type="application/pdf",
        content=content,
        actor=clinical_user,
        scanner=_CleanScanner(),
    )
    path = LocalClinicalObjectStorage._path(document.object_key)
    assert path.read_bytes() == content

    key = _key()
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": key}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    dry_run = io.StringIO()
    call_command("migrate_clinical_objects_encryption", stdout=dry_run)
    assert "1 clinical objects require" in dry_run.getvalue()
    assert path.read_bytes() == content

    call_command("migrate_clinical_objects_encryption", "--apply", stdout=io.StringIO())
    assert path.read_bytes() != content
    document.refresh_from_db()
    assert document.metadata["at_rest_encryption"]["key_id"] == "k1"
    token = LocalClinicalObjectStorage.signed_token(document=document, actor=clinical_user)
    assert (
        LocalClinicalObjectStorage.read(token=token, actor=clinical_user, tenant_id=str(clinical_setup["tenant"].id))
        == content
    )
    assert DocumentAccessEvent.all_objects.filter(document=document, outcome="SUCCESS").exists()


def test_encryption_migration_preflight_stops_on_tampered_object(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    key = _key()
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": key}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    settings.DAWATRACE_ENV = "development"
    document = LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="tampered.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nintact",
        actor=clinical_user,
        scanner=_CleanScanner(),
    )
    path = LocalClinicalObjectStorage._path(document.object_key)
    path.write_bytes(b"tampered")
    with pytest.raises(CommandError, match="integrity verification"):
        call_command("migrate_clinical_objects_encryption", "--apply", stdout=io.StringIO())
    assert path.read_bytes() == b"tampered"


def test_encryption_migration_repairs_metadata_for_active_key(settings, tmp_path, clinical_setup, clinical_user):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_ENV = "production"
    key = _key()
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"k1": key}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "k1"
    document = LocalClinicalObjectStorage.store(
        tenant_id=clinical_setup["tenant"].id,
        patient=clinical_setup["patient"],
        original_name="metadata.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4\nmetadata repair",
        actor=clinical_user,
        scanner=_CleanScanner(),
    )
    path = LocalClinicalObjectStorage._path(document.object_key)
    original_bytes = path.read_bytes()
    document.metadata = {}
    document.save(update_fields=["metadata", "updated_at"])

    dry_run = io.StringIO()
    call_command("migrate_clinical_objects_encryption", stdout=dry_run)
    assert "1 clinical objects require" in dry_run.getvalue()
    call_command("migrate_clinical_objects_encryption", "--apply", stdout=io.StringIO())

    document.refresh_from_db()
    assert path.read_bytes() == original_bytes
    assert document.metadata["at_rest_encryption"]["key_id"] == "k1"
