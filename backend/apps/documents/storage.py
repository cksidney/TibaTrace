from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError

from apps.documents.encryption import (
    DocumentEncryptionError,
    decrypt_document_bytes,
    encrypt_document_bytes,
    validate_document_keyring,
)
from apps.documents.models import DocumentAccessEvent, StoredClinicalDocument


class MalwareScanner:
    """Integration point. Production must replace the default unavailable scanner."""

    def scan(self, content: bytes) -> str:
        from apps.documents.scanning import ClamAVScanner

        if getattr(settings, "DAWATRACE_MALWARE_SCANNER_HOST", ""):
            return ClamAVScanner().scan(content)
        return "NOT_CONFIGURED"


class LocalClinicalObjectStorage:
    capability = "documents.read"

    @staticmethod
    def _root() -> Path:
        return Path(settings.MEDIA_ROOT).resolve()

    @classmethod
    def _path(cls, key: str) -> Path:
        root = cls._root()
        candidate = (root / key).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValidationError("Invalid object key.")
        return candidate

    @staticmethod
    def _encryption_config(*, required: bool = False) -> tuple[dict[str, str], str]:
        keyring = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS", {}) or {}
        active_key_id = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID", "") or ""
        if not keyring and not active_key_id and not required:
            return {}, ""
        try:
            validate_document_keyring(keyring, active_key_id)
        except DocumentEncryptionError as exc:
            raise ValidationError("Clinical-document encryption is not configured safely.") from exc
        return keyring, active_key_id

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".clinical-object-", delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @classmethod
    def _stored_bytes(cls, content: bytes, *, object_key: str) -> tuple[bytes, str | None]:
        keyring, active_key_id = cls._encryption_config(required=settings.DAWATRACE_ENV == "production")
        if not keyring:
            return content, None
        encrypted = encrypt_document_bytes(
            content,
            key_id=active_key_id,
            key=keyring[active_key_id],
            associated_data=object_key,
        )
        return encrypted, active_key_id

    @classmethod
    def _decrypt_path(cls, path: Path, *, object_key: str) -> tuple[bytes, str | None]:
        keyring, _ = cls._encryption_config(required=settings.DAWATRACE_ENV == "production")
        try:
            return decrypt_document_bytes(path.read_bytes(), keyring=keyring, associated_data=object_key)
        except DocumentEncryptionError as exc:
            raise ValidationError("Stored clinical object cannot be decrypted safely.") from exc

    @classmethod
    def store(
        cls, *, tenant_id, patient, original_name: str, content_type: str, content: bytes, actor, scanner=None
    ) -> StoredClinicalDocument:
        if not tenant_id or str(patient.tenant_id) != str(tenant_id) or str(actor.tenant_id) != str(tenant_id):
            raise PermissionDenied("Tenant-owned patient and actor are required.")
        allowed = set(settings.DAWATRACE_DOCUMENT_ALLOWED_CONTENT_TYPES)
        if content_type not in allowed:
            raise ValidationError("Document content type is not allowed.")
        if len(content) > settings.DAWATRACE_DOCUMENT_MAX_BYTES:
            raise ValidationError("Document exceeds the configured size limit.")
        guessed, _ = mimetypes.guess_type(original_name)
        if guessed and guessed != content_type:
            raise ValidationError("Document extension does not match its content type.")
        digest = hashlib.sha256(content).hexdigest()
        key = f"tenant/{tenant_id}/clinical/{patient.id}/{digest}/{Path(original_name).name}"
        path = cls._path(key)
        scan_status = (scanner or MalwareScanner()).scan(content)
        if scan_status in {"INFECTED", "ERROR"}:
            raise ValidationError("The document failed malware scanning or the scanner is unavailable.")
        if settings.DAWATRACE_ENV == "production" and scan_status != "CLEAN":
            raise ValidationError("Clinical document upload requires a clean malware scan in production.")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        stored_bytes, encryption_key_id = cls._stored_bytes(content, object_key=key)
        if path.exists():
            existing_plaintext, existing_key_id = cls._decrypt_path(path, object_key=key)
            if len(existing_plaintext) != len(content) or hashlib.sha256(existing_plaintext).hexdigest() != digest:
                raise ValidationError("Existing clinical object failed integrity verification.")
            if encryption_key_id and existing_key_id != encryption_key_id:
                cls._write_atomic(path, stored_bytes)
        else:
            cls._write_atomic(path, stored_bytes)
        metadata = {}
        if encryption_key_id:
            metadata["at_rest_encryption"] = {
                "algorithm": "AES-256-GCM",
                "key_id": encryption_key_id,
                "version": 1,
            }
        document, _created = StoredClinicalDocument.all_objects.get_or_create(
            tenant_id=tenant_id,
            object_key=key,
            defaults={"patient": patient, "original_name": Path(original_name).name, "content_type": content_type,
                      "size_bytes": len(content), "hash_sha256": digest, "uploaded_by": actor,
                      "malware_scan_status": scan_status, "metadata": metadata},
        )
        if not _created:
            # A repeated upload may rescan or rotate the same object. Keep its
            # evidence consistent with the bytes now stored under its key.
            document.malware_scan_status = scan_status
            document.metadata = {**document.metadata, **metadata}
            document.save(update_fields=["malware_scan_status", "metadata", "updated_at"])
        DocumentAccessEvent.all_objects.create(
            tenant_id=tenant_id, document=document, actor=actor, action="UPLOAD", outcome="SUCCESS"
        )
        return document

    @staticmethod
    def signed_token(*, document: StoredClinicalDocument, actor, expires_seconds: int = 300) -> str:
        if not actor.has_capability("documents.read", tenant_id=document.tenant_id):
            raise PermissionDenied("Document read capability is required.")
        return signing.dumps(
            {"document_id": str(document.id), "tenant_id": str(document.tenant_id), "actor_id": str(actor.id)},
            salt="dawatrace.document",
            compress=True,
        )

    @classmethod
    def read(cls, *, token: str, actor, tenant_id: str, max_age: int = 300) -> bytes:
        try:
            payload = signing.loads(token, salt="dawatrace.document", max_age=max_age)
        except signing.BadSignature as exc:
            raise PermissionDenied("Document token is invalid or expired.") from exc
        if payload.get("tenant_id") != str(tenant_id) or payload.get("actor_id") != str(actor.id):
            raise PermissionDenied("Document token is outside the active tenant or actor scope.")
        if not actor.has_capability("documents.read", tenant_id=tenant_id):
            raise PermissionDenied("Document read capability is required.")
        document = StoredClinicalDocument.all_objects.filter(
            id=payload.get("document_id"), tenant_id=tenant_id
        ).first()
        if not document:
            raise FileNotFoundError("Document is unavailable in the active tenant.")
        path = cls._path(document.object_key)
        if not path.exists():
            raise FileNotFoundError("Stored object is missing.")
        try:
            content, _ = cls._decrypt_path(path, object_key=document.object_key)
        except ValidationError:
            DocumentAccessEvent.all_objects.create(
                tenant_id=tenant_id,
                document=document,
                actor=actor,
                action="DOWNLOAD",
                outcome="DECRYPTION_FAILED",
            )
            raise
        if len(content) != document.size_bytes or hashlib.sha256(content).hexdigest() != document.hash_sha256:
            DocumentAccessEvent.all_objects.create(
                tenant_id=tenant_id, document=document, actor=actor, action="DOWNLOAD", outcome="HASH_MISMATCH"
            )
            raise ValidationError("Stored object failed integrity verification.")
        DocumentAccessEvent.all_objects.create(
            tenant_id=tenant_id, document=document, actor=actor, action="DOWNLOAD", outcome="SUCCESS"
        )
        return content
