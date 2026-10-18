from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.documents.encryption import (
    DocumentEncryptionError,
    decrypt_document_bytes,
    encrypt_document_bytes,
    validate_document_keyring,
)
from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage


class Command(BaseCommand):
    help = "Encrypt existing clinical objects with the active versioned document key. Dry-run unless --apply is set."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Atomically encrypt objects after a full preflight.")
        parser.add_argument("--tenant-id", help="Restrict the migration to one tenant UUID.")

    def handle(self, *args, **options):
        keyring = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS", {}) or {}
        active_key_id = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID", "") or ""
        try:
            validate_document_keyring(keyring, active_key_id)
        except DocumentEncryptionError as exc:
            raise CommandError("A valid active clinical-document encryption keyring is required.") from exc

        documents = StoredClinicalDocument.all_objects.order_by("pk")
        if options.get("tenant_id"):
            documents = documents.filter(tenant_id=options["tenant_id"])

        pending = 0
        for document in documents.iterator(chunk_size=500):
            path = LocalClinicalObjectStorage._path(document.object_key)
            if not path.is_file():
                raise CommandError(f"Preflight failed: object {document.pk} is missing.")
            try:
                plaintext, key_id = decrypt_document_bytes(
                    path.read_bytes(), keyring=keyring, associated_data=document.object_key
                )
            except DocumentEncryptionError as exc:
                raise CommandError(f"Preflight failed: object {document.pk} cannot be decrypted.") from exc
            digest = hashlib.sha256(plaintext).hexdigest()
            if len(plaintext) != document.size_bytes or digest != document.hash_sha256:
                raise CommandError(f"Preflight failed: object {document.pk} failed integrity verification.")
            metadata = document.metadata or {}
            if not isinstance(metadata, dict):
                raise CommandError(f"Preflight failed: object {document.pk} has invalid encryption metadata.")
            expected_metadata = {
                "algorithm": "AES-256-GCM",
                "key_id": active_key_id,
                "version": 1,
            }
            current_metadata = metadata.get("at_rest_encryption")
            if key_id != active_key_id or current_metadata != expected_metadata:
                pending += 1

        if not options["apply"]:
            self.stdout.write(
                f"Dry run complete. {pending} clinical objects require encryption, key rotation, or metadata repair; no files changed."
            )
            self.stdout.write("Review the preflight and recent protected backups, then rerun with --apply to write.")
            return

        changed = 0
        for document in documents.iterator(chunk_size=500):
            path = LocalClinicalObjectStorage._path(document.object_key)
            try:
                plaintext, current_key_id = decrypt_document_bytes(
                    path.read_bytes(), keyring=keyring, associated_data=document.object_key
                )
            except DocumentEncryptionError as exc:
                raise CommandError(f"Write aborted: object {document.pk} cannot be decrypted.") from exc
            digest = hashlib.sha256(plaintext).hexdigest()
            if len(plaintext) != document.size_bytes or digest != document.hash_sha256:
                raise CommandError(f"Write aborted: object {document.pk} failed integrity verification.")
            metadata = document.metadata or {}
            if not isinstance(metadata, dict):
                raise CommandError(f"Write aborted: object {document.pk} has invalid encryption metadata.")
            expected_metadata = {
                "algorithm": "AES-256-GCM",
                "key_id": active_key_id,
                "version": 1,
            }
            metadata_changed = metadata.get("at_rest_encryption") != expected_metadata
            if current_key_id == active_key_id and not metadata_changed:
                continue
            if current_key_id != active_key_id:
                encrypted = encrypt_document_bytes(
                    plaintext,
                    key_id=active_key_id,
                    key=keyring[active_key_id],
                    associated_data=document.object_key,
                )
                LocalClinicalObjectStorage._write_atomic(path, encrypted)
                changed += 1
            metadata["at_rest_encryption"] = expected_metadata
            document.metadata = metadata
            document.save(update_fields=["metadata", "updated_at"])

        self.stdout.write(
            f"Encrypted or rotated {changed} clinical objects with key ID {active_key_id}; "
            "encryption metadata is synchronized."
        )
