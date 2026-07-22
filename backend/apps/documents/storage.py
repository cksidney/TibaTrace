from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError

from apps.documents.models import DocumentAccessEvent, StoredClinicalDocument


class MalwareScanner:
    """Integration point. Production must replace the default unavailable scanner."""

    def scan(self, content: bytes) -> str:
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
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        scan_status = (scanner or MalwareScanner()).scan(content)
        document = StoredClinicalDocument.all_objects.create(
            tenant_id=tenant_id,
            patient=patient,
            object_key=key,
            original_name=Path(original_name).name,
            content_type=content_type,
            size_bytes=len(content),
            hash_sha256=digest,
            uploaded_by=actor,
            malware_scan_status=scan_status,
        )
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
        content = path.read_bytes()
        if len(content) != document.size_bytes or hashlib.sha256(content).hexdigest() != document.hash_sha256:
            DocumentAccessEvent.all_objects.create(
                tenant_id=tenant_id, document=document, actor=actor, action="DOWNLOAD", outcome="HASH_MISMATCH"
            )
            raise ValidationError("Stored object failed integrity verification.")
        DocumentAccessEvent.all_objects.create(
            tenant_id=tenant_id, document=document, actor=actor, action="DOWNLOAD", outcome="SUCCESS"
        )
        return content
