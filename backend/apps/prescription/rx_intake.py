import base64
import binascii
import hashlib
import json
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage
from apps.medicines.models import CommercialSKU
from apps.medicines.provisioning import _is_controlled
from apps.patients.models import Patient
from apps.pos_shift.models import PosRegister
from apps.practitioners.models import Practitioner
from apps.prescription.models import Prescription
from apps.prescription.rx_intake_models import PrescriptionIntakeReceipt, PrescriptionSourceDocument
from apps.prescription.services.clinical_dispensing import PrescriptionIntakeService, _require_capability

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FILES = 5
READ_CAPABILITIES = ("prescriptions.intake", "prescriptions.legal_validate", "prescriptions.clinical_review", "prescriptions.pharmacist_verify", "dispensing.reserve")


def source_uploads_available():
    return bool(settings.DAWATRACE_RX_SOURCE_UPLOADS_ENABLED and
                (settings.DAWATRACE_ENV != "production" or not settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED
                 or settings.DAWATRACE_MALWARE_SCANNER_HOST))


def device_branch(*, tenant, actor, device_id):
    if not tenant.may_operate or str(actor.tenant_id) != str(tenant.pk) or not actor.is_active:
        raise PermissionDenied("Use an active operator in this tenant.")
    registers = list(PosRegister.all_objects.filter(tenant=tenant, device_id=device_id).select_related("location")[:2])
    if not device_id or len(registers) != 1 or registers[0].state == "RETIRED" or registers[0].location.status != "ACTIVE":
        raise ValidationError("An active branch-bound POS device is required for prescription intake.")
    branch = registers[0].location
    branches = (actor.metadata or {}).get("branch_ids")
    if branches is not None and not actor.is_superuser and str(branch.pk) not in [str(value) for value in branches]:
        raise PermissionDenied("This branch is outside the operator's assignment.")
    if not any(actor.has_capability(capability, tenant_id=tenant.pk) for capability in READ_CAPABILITIES):
        raise PermissionDenied("Prescription intake or clinical review authority is required.")
    return branch


def decode_attachments(rows):
    if len(rows) > MAX_FILES:
        raise ValidationError("Attach at most five source files.")
    decoded, total, seen = [], 0, set()
    for row in rows:
        name, mime = row["name"], row["content_type"]
        if PurePath(name).name != name or "\\" in name or not name.strip() or len(name.encode("utf-8")) > 180 or any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValidationError("Use a short, plain source filename without control characters.")
        encoded = row["content_base64"]
        if len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
            raise ValidationError("Each source file must be at most 5 MB.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValidationError("The source file encoding is invalid.") from None
        valid = ((mime == "application/pdf" and name.lower().endswith(".pdf") and content.startswith(b"%PDF-") and b"%%EOF" in content[-2048:])
                 or (mime == "image/jpeg" and name.lower().endswith((".jpg", ".jpeg")) and content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"))
                 or (mime == "image/png" and name.lower().endswith(".png") and content.startswith(b"\x89PNG\r\n\x1a\n") and content.endswith(b"IEND\xaeB`\x82")))
        total += len(content)
        if not valid or not content or len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValidationError("Use genuine JPEG, PNG or PDF source files, up to 5 MB each and 8 MB total.")
        digest = hashlib.sha256(content).hexdigest()
        if (name, digest) in seen:
            raise ValidationError("Attach each source file only once.")
        seen.add((name, digest))
        decoded.append({"name": name, "content_type": mime, "content": content, "hash": digest})
    return decoded


class PosPrescriptionIntakeService:
    @staticmethod
    def receive(*, tenant, branch, actor, device_id, command, provider_code="", external_reference=""):
        _require_capability(actor, tenant.pk, "prescriptions.intake")
        files = decode_attachments(command.get("attachments", []))
        if files:
            _require_capability(actor, tenant.pk, "documents.write")
            if not source_uploads_available():
                raise ValidationError("Photo/PDF intake is temporarily unavailable. Enter the prescription directly and retain the original for pharmacist review.")
        if not files and not command.get("original_available"):
            raise ValidationError("Attach the original prescription or confirm the genuine original is available for review.")
        fingerprint = {key: value for key, value in command.items() if key not in {"attachments", "idempotency_key", "device_id"}}
        fingerprint.update({"branch": str(branch.pk), "provider": provider_code, "external_reference": external_reference,
                            "attachments": [{"name": row["name"], "hash": row["hash"]} for row in files]})
        digest = hashlib.sha256(json.dumps(fingerprint, default=str, sort_keys=True).encode()).hexdigest()
        key = command["idempotency_key"]
        source_key = f"{provider_code}:{external_reference}" if provider_code else f"PAPER:{command['prescription_number']}"
        if len(source_key) > 160:
            raise ValidationError("The original prescription reference is too long.")
        with transaction.atomic():
            # Tenant lock serializes original-source and command-key retries,
            # including two tills importing the same source concurrently.
            type(tenant).objects.select_for_update().get(pk=tenant.pk)
            receipt = PrescriptionIntakeReceipt.all_objects.filter(tenant=tenant, idempotency_key=key).first()
            if receipt:
                if receipt.payload_hash != digest or receipt.actor_id != actor.pk or receipt.device_id != device_id:
                    raise ValidationError("This intake retry key belongs to a different command.")
                return receipt.prescription
            receipt = PrescriptionIntakeReceipt.all_objects.filter(tenant=tenant, source_key=source_key).first()
            if receipt:
                if receipt.payload_hash != digest:
                    raise ValidationError("This original prescription was already received with different details. Review that record.")
                return receipt.prescription
            patient = Patient.all_objects.filter(tenant=tenant, pk=command["patient"], is_active=True, is_deceased=False).first()
            practitioner = Practitioner.all_objects.filter(tenant=tenant, pk=command["practitioner"], status="ACTIVE").first()
            if not patient or not practitioner:
                raise ValidationError("Select an active patient and prescriber from this tenant.")
            items = []
            for row in command["items"]:
                sku = CommercialSKU.all_objects.filter(tenant=tenant, pk=row["sku"], status="ACTIVE").select_related(
                    "package_definition", "manufactured_product__clinical_product__dose_form"
                ).first()
                if not sku:
                    raise ValidationError("Every prescribed product must be an active governed SKU in this tenant.")
                items.append({"prescribed_sku": sku, "medication_name": sku.display_name,
                              "quantity": row["quantity"], "unit": sku.package_definition.unit_of_measure,
                              "dosage_instruction": row["directions"], "is_controlled": _is_controlled(sku)})
            number = command["prescription_number"]
            source_reference = source_key if provider_code else number
            if Prescription.all_objects.filter(tenant=tenant, prescription_number=number).exists() or Prescription.all_objects.filter(
                tenant=tenant, external_prescription_reference=source_reference
            ).exists():
                raise ValidationError("This prescription reference already exists. Open the existing record before receiving it again.")
            documents = [LocalClinicalObjectStorage.store(tenant_id=tenant.pk, patient=patient,
                         original_name=row["name"], content_type=row["content_type"], content=row["content"], actor=actor) for row in files]
            rx = PrescriptionIntakeService.receive(
                tenant=tenant, actor=actor, patient=patient, practitioner=practitioner,
                organization=branch.organization, location=branch, prescription_number=number,
                external_prescription_reference=source_reference, prescription_date=command["prescription_date"],
                prescription_type=command["prescription_type"], source_channel="HOSPITAL_INTEGRATION" if provider_code else "PAPER",
                original_document=documents[0] if documents else None, items=items,
                is_controlled_medicine=any(row["is_controlled"] for row in items), notes=command.get("notes", ""),
                metadata={"intake_surface": "POS", "provider": provider_code,
                          "original_reference": external_reference or number, "original_available": bool(command.get("original_available"))},
            )
            for document in documents:
                PrescriptionSourceDocument.all_objects.create(tenant=tenant, prescription=rx, document=document)
            PrescriptionIntakeReceipt.all_objects.create(tenant=tenant, prescription=rx, branch=branch, actor=actor,
                device_id=device_id, idempotency_key=key, source_key=source_key, payload_hash=digest, provider_code=provider_code)
            return rx


def source_documents(rx):
    documents = list(StoredClinicalDocument.all_objects.filter(tenant_id=rx.tenant_id, patient_id=rx.patient_id, prescriptionsourcedocument__prescription=rx))
    if rx.original_document_id and rx.original_document.patient_id == rx.patient_id and all(row.pk != rx.original_document_id for row in documents):
        documents.append(rx.original_document)
    return [{"id": str(row.pk), "name": row.original_name, "content_type": row.content_type,
             "size_bytes": row.size_bytes, "sha256": row.hash_sha256, "malware_scan_status": row.malware_scan_status} for row in documents]
