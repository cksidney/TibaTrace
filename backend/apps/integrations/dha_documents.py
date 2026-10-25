"""Resolve governed patient documents for multipart submission; never arbitrary disk paths."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage
from apps.integrations.dha_workflows import authorize


def documents_for_exchange(connection, visit, actor, rows, *, read=False):
    if not isinstance(rows, list) or len(rows) > 5:
        raise ValidationError("Select at most five stored patient documents.")
    if not rows:
        return []
    authorize(connection, actor, "documents.read")
    parts, total, seen = [], 0, set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("Use a stored document ID and multipart field name.")
        field = row.get("field_name", "file_blob")
        if not isinstance(field, str) or not re.fullmatch(r"(?:file_blob|attachments_\d+_file_blob)", field) or field in seen:
            raise ValidationError("Each attachment requires a unique valid file field.")
        seen.add(field)
        allowed_scans = ["CLEAN"] if settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED else ["CLEAN", "NOT_SCANNED"]
        document = StoredClinicalDocument.all_objects.filter(pk=row.get("document_id"), tenant_id=connection.tenant_id,
            patient_id=visit.patient_id, malware_scan_status__in=allowed_scans).first()
        if not document or document.size_bytes > 5 * 1024 * 1024 or document.content_type not in {"application/pdf", "image/png", "image/jpeg"}:
            raise ValidationError("Use an eligible JPEG, PNG or PDF belonging to this patient, up to 5 MB. Required malware scans must be clean.")
        total += document.size_bytes
        if total > 10 * 1024 * 1024:
            raise ValidationError("The combined attachments exceed 10 MB.")
        if read:
            content = LocalClinicalObjectStorage.read(token=LocalClinicalObjectStorage.signed_token(document=document, actor=actor),
                actor=actor, tenant_id=str(connection.tenant_id))
            parts.append((field, (document.original_name, content, document.content_type)))
            if document.malware_scan_status == "NOT_SCANNED":
                from apps.audit.service import log_audit
                log_audit(tenant_id=connection.tenant_id, actor_id=actor.pk, action="DHA_DOCUMENT_EXPORT_SCAN_DEFERRED",
                    model_name="StoredClinicalDocument", object_id=document.pk,
                    metadata={"connection": str(connection.pk), "scan_status": "NOT_SCANNED"})
    return parts
