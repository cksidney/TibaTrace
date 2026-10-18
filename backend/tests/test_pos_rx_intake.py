import base64
import copy
import json
from decimal import Decimal

import pytest
from django.utils import timezone
from tests.test_pos_enterprise_dispensing import grant
from tests.test_pos_retail_transactions import world  # noqa: F401

from apps.customers.models import Customer
from apps.documents.models import DocumentAccessEvent, StoredClinicalDocument
from apps.documents.storage import MalwareScanner
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.prescription.models import ClinicalWorkItem, DispensingEpisode, Prescription
from apps.prescription.pos_dispensing_api.intake import PosPrescriptionIntakeViewSet
from apps.prescription.rx_feeds import FEED_ADAPTERS
from apps.prescription.rx_intake_models import PrescriptionIntakeReceipt, PrescriptionSourceDocument
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db
BASE = "/api/pos/dispensing/intake/"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=")


@pytest.fixture
def intake(world, settings, tmp_path, monkeypatch):  # noqa: F811
    settings.MEDIA_ROOT = str(tmp_path)
    settings.DAWATRACE_RX_SOURCE_UPLOADS_ENABLED = True
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = True
    settings.DAWATRACE_MALWARE_SCANNER_HOST = "test-scanner"
    monkeypatch.setattr(MalwareScanner, "scan", lambda self, content: "CLEAN")
    world["client"].credentials(HTTP_X_TENANT_ID=str(world["tenant"].pk))
    patient = Patient.all_objects.create(tenant=world["tenant"], patient_number="RX-PAT-01", internal_reference_id="RX-PAT-01", first_name="Amina", last_name="Test")
    prescriber = Practitioner.all_objects.create(tenant=world["tenant"], first_name="Doctor", last_name="Test", registration_number="RX-DR-01", status="ACTIVE")
    command = {"device_id": "POS-RETAIL-01", "idempotency_key": "rx-command-01", "patient": str(patient.pk),
        "practitioner": str(prescriber.pk), "prescription_number": "ORIGINAL-RX-01", "prescription_date": str(timezone.localdate()),
        "prescription_type": "ACUTE", "original_available": True,
        "items": [{"sku": str(world["sku"].pk), "quantity": "2.000", "directions": "One tablet twice daily as prescribed."}],
        "attachments": [{"name": "prescription.png", "content_type": "image/png", "content_base64": base64.b64encode(PNG).decode()}]}
    return {**world, "patient": patient, "prescriber": prescriber, "command": command}


def post(intake, path=BASE, command=None):
    return intake["client"].post(path, command or intake["command"], format="json")


def test_native_intake_persists_original_and_starts_unverified_review(intake):
    response = post(intake)
    assert response.status_code == 201, response.data
    rx = Prescription.all_objects.get(pk=response.data["id"])
    assert rx.status == "RECEIVED" and rx.legal_validation_state == "PENDING"
    assert rx.clinical_review_state == "NOT_STARTED" and rx.pharmacist_verification_state == "NOT_VERIFIED"
    assert rx.original_document.patient_id == intake["patient"].pk
    assert PrescriptionSourceDocument.all_objects.filter(prescription=rx).count() == 1
    assert ClinicalWorkItem.all_objects.filter(prescription=rx, queue_type="LEGAL_VALIDATION", status="OPEN").exists()
    assert not DispensingEpisode.all_objects.exists()
    viewed = post(intake, f"{BASE}{rx.pk}/source-document/", {"device_id": "POS-RETAIL-01", "document_id": str(rx.original_document_id)})
    assert viewed.status_code == 200, viewed.data
    assert base64.b64decode(viewed.data["content_base64"]) == PNG
    assert DocumentAccessEvent.all_objects.filter(document=rx.original_document, action="DOWNLOAD", outcome="SUCCESS").exists()


def test_original_intake_replay_is_idempotent_and_rejects_changed_details(intake):
    first = post(intake)
    assert first.status_code == 201, first.data
    assert post(intake).data["id"] == first.data["id"]
    changed = copy.deepcopy(intake["command"])
    changed["items"][0]["quantity"] = "3.000"
    assert post(intake, command=changed).status_code == 400
    assert Prescription.all_objects.count() == 1 and PrescriptionIntakeReceipt.all_objects.count() == 1
    check = intake["client"].get(f"{BASE}reconcile/", {"device_id": "POS-RETAIL-01", "idempotency_key": "rx-command-01"})
    assert check.status_code == 200 and check.data["found"] is True


@pytest.mark.parametrize("kind", ["patient", "practitioner", "sku"])
def test_native_intake_rejects_foreign_or_unknown_clinical_identity(intake, kind):
    command = copy.deepcopy(intake["command"])
    import uuid
    if kind == "sku":
        command["items"][0]["sku"] = str(uuid.uuid4())
    else:
        other = Tenant.objects.create(name="Other RX tenant", slug=f"other-rx-{kind}")
        record = Patient.all_objects.create(tenant=other, internal_reference_id="OTHER-RX", first_name="Other", last_name="Patient") if kind == "patient" else Practitioner.all_objects.create(tenant=other, first_name="Other", last_name="Doctor")
        command[kind] = str(record.pk)
    result = post(intake, command=command)
    assert result.status_code == 400, result.data
    assert not Prescription.all_objects.exists() and not StoredClinicalDocument.all_objects.exists()


@pytest.mark.parametrize("bad_file", [
    {"name": "fake.pdf", "content_type": "application/pdf", "content_base64": base64.b64encode(b"not a PDF").decode()},
    {"name": "../rx.png", "content_type": "image/png", "content_base64": base64.b64encode(PNG).decode()},
    {"name": "rx.png", "content_type": "image/png", "content_base64": "not_base64"},
    {"name": "rx.svg", "content_type": "image/svg+xml", "content_base64": ""},
    {"name": "病" * 100 + ".png", "content_type": "image/png", "content_base64": base64.b64encode(PNG).decode()},
])
def test_native_intake_rejects_invalid_source_files_without_creating_rx(intake, bad_file):
    command = copy.deepcopy(intake["command"])
    command["attachments"] = [bad_file]
    assert post(intake, command=command).status_code == 400
    assert not Prescription.all_objects.exists() and not StoredClinicalDocument.all_objects.exists()


@pytest.mark.parametrize("scan_status", ["INFECTED", "ERROR", "NOT_CONFIGURED"])
def test_production_upload_fails_closed_without_a_clean_malware_result(intake, settings, monkeypatch, scan_status):
    settings.DAWATRACE_ENV = "production"
    monkeypatch.setattr(MalwareScanner, "scan", lambda self, content: scan_status)
    result = post(intake)
    assert result.status_code == 400, result.data
    assert not Prescription.all_objects.exists() and not StoredClinicalDocument.all_objects.exists()


def test_intake_requires_role_branch_and_source_evidence(intake):
    user = intake["operator"]
    user.is_superuser = False
    user.save()
    assert post(intake).status_code == 403
    grant(user, intake["tenant"], ["prescriptions.intake"], "RX_INTAKE_ONLY")
    assert post(intake).status_code == 403  # document writes are a separate capability
    command = copy.deepcopy(intake["command"])
    command["attachments"] = []
    command["original_available"] = False
    assert post(intake, command=command).status_code == 400
    command["original_available"] = True
    user.metadata = {"branch_ids": []}
    user.save()
    assert post(intake, command=command).status_code == 403
    assert not Prescription.all_objects.exists()


def test_intake_cannot_skip_pharmacist_review(intake):
    result = post(intake)
    response = post(intake, f"{BASE}{result.data['id']}/progress/", {"device_id": "POS-RETAIL-01", "operation": "verify"})
    assert response.status_code == 400
    rx = Prescription.all_objects.get(pk=result.data["id"])
    assert rx.pharmacist_verification_state == "NOT_VERIFIED"


@pytest.mark.parametrize("provider", ["DHA", "HOSPITAL_EMR"])
def test_tenant_feed_import_maps_identity_and_never_trusts_source_approval(intake, monkeypatch, provider):
    calls = []
    class Adapter:
        def __init__(self, *, tenant, provider, config, credentials):
            assert tenant.pk == intake["tenant"].pk and credentials["api_key"] == "test-feed-secret"
        def validate_configuration(self, *, tenant):
            pass
        def fetch_prescription(self, reference):
            calls.append(reference)
            return {"reference": reference, "patient_reference": "EXT-PAT", "prescriber_reference": "EXT-DR",
                "prescription_date": str(timezone.localdate()), "prescription_type": "ACUTE", "status": "VERIFIED",
                "items": [{"product_reference": "EXT-DRUG", "quantity": "2", "directions": "Original source directions"}]}
    monkeypatch.setitem(FEED_ADAPTERS, "TEST_EMR", Adapter)
    monkeypatch.setenv("TEST_RX_FEED_API_KEY", "test-feed-secret")
    monkeypatch.setenv("TIBATRACE_RX_CONNECTIONS", json.dumps({str(intake["tenant"].pk): {provider: {
        "enabled": True, "validated": True, "adapter_code": "TEST_EMR", "credentials_env": {"api_key": "TEST_RX_FEED_API_KEY"},
        "patient_map": {"EXT-PAT": str(intake["patient"].pk)}, "prescriber_map": {"EXT-DR": str(intake["prescriber"].pk)},
        "product_map": {"EXT-DRUG": str(intake["sku"].pk)}}}}))
    command = {"device_id": "POS-RETAIL-01", "idempotency_key": "feed-command", "provider": provider, "reference": "EXTERNAL-RX-01"}
    result = post(intake, f"{BASE}import/", command)
    assert result.status_code == 201, result.data
    assert result.data["verification_state"] == "NOT_VERIFIED" and result.data["legal_state"] == "PENDING"
    assert "test-feed-secret" not in str(result.data)
    monkeypatch.setenv("TIBATRACE_RX_CONNECTIONS", "{}")
    replay = post(intake, f"{BASE}import/", command)
    assert replay.status_code == 200 and replay.data["id"] == result.data["id"]
    assert len(calls) == 1 and Prescription.all_objects.count() == 1


def test_unconfigured_feed_does_not_invent_prescriptions(intake, monkeypatch):
    monkeypatch.setenv("TIBATRACE_RX_CONNECTIONS", "{}")
    result = post(intake, f"{BASE}import/", {"device_id": "POS-RETAIL-01", "idempotency_key": "feed-command", "provider": "DHA", "reference": "RX-1"})
    assert result.status_code == 400
    assert not Prescription.all_objects.exists()


def test_duplicate_source_and_attachment_are_not_duplicated(intake):
    first = post(intake)
    retry = copy.deepcopy(intake["command"])
    retry["idempotency_key"] = "new-command-same-original"
    assert post(intake, command=retry).data["id"] == first.data["id"]
    assert Prescription.all_objects.count() == 1
    duplicate = copy.deepcopy(intake["command"])
    duplicate["attachments"] *= 2
    assert post(intake, command=duplicate).status_code == 400


def test_source_download_requires_document_capability_and_device_alignment(intake):
    created = post(intake)
    document = created.data["documents"][0]["id"]
    user = intake["operator"]
    user.is_superuser = False
    user.save()
    grant(user, intake["tenant"], ["prescriptions.intake"], "RX_VIEW_ONLY")
    result = post(intake, f"{BASE}{created.data['id']}/source-document/", {"device_id": "POS-RETAIL-01", "document_id": document})
    assert result.status_code == 403
    intake["client"].credentials(HTTP_X_TENANT_ID=str(intake["tenant"].pk), HTTP_X_POS_DEVICE_ID="different-device")
    assert post(intake).status_code == 400


def test_paper_intake_accepts_confirmed_physical_original_without_upload(intake):
    command = copy.deepcopy(intake["command"])
    command["attachments"] = []
    result = post(intake, command=command)
    assert result.status_code == 201, result.data
    assert result.data["documents"] == [] and result.data["verification_state"] == "NOT_VERIFIED"


def test_production_manual_intake_works_with_uploads_deferred_and_no_scanner(intake, settings, monkeypatch):
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_RX_SOURCE_UPLOADS_ENABLED = False
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"test-key": base64.urlsafe_b64encode(b"x" * 32).decode()}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "test-key"
    def should_not_scan(self, content):
        raise AssertionError("Generated structured records must not invoke the upload scanner")
    monkeypatch.setattr(MalwareScanner, "scan", should_not_scan)
    choices = intake["client"].get(f"{BASE}options/", {"device_id": "POS-RETAIL-01"})
    assert choices.status_code == 200 and choices.data["capabilities"]["receive"] is True
    assert choices.data["capabilities"]["upload"] is False and "temporarily unavailable" in choices.data["upload_notice"]
    assert post(intake).status_code == 400
    assert not StoredClinicalDocument.all_objects.exists()
    command = copy.deepcopy(intake["command"])
    command["attachments"] = []
    result = post(intake, command=command)
    assert result.status_code == 201, result.data
    assert result.data["verification_state"] == "NOT_VERIFIED"
    document = StoredClinicalDocument.all_objects.get()
    assert document.malware_scan_status == "NOT_APPLICABLE"
    assert document.metadata["content_origin"] == "SYSTEM_GENERATED_JSON"
    assert document.metadata["malware_scanning_performed"] is False
    assert document.metadata["at_rest_encryption"]["key_id"] == "test-key"


def test_enabling_upload_flag_alone_does_not_enable_production_uploads(intake, settings):
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    result = post(intake)
    assert result.status_code == 400 and not Prescription.all_objects.exists()


def test_explicit_scan_deferral_keeps_uploads_encrypted_unscanned_and_unverified(intake, settings, monkeypatch):
    settings.DAWATRACE_ENV = "production"
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = False
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"test-key": base64.urlsafe_b64encode(b"x" * 32).decode()}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "test-key"
    def should_not_scan(self, content):
        raise AssertionError("Deferred scanning must not claim a scanner was called")
    monkeypatch.setattr(MalwareScanner, "scan", should_not_scan)
    choices = intake["client"].get(f"{BASE}options/", {"device_id": "POS-RETAIL-01"})
    assert choices.status_code == 200 and choices.data["capabilities"]["upload"] is True
    assert "not malware scanned" in choices.data["upload_notice"]
    result = post(intake)
    assert result.status_code == 201, result.data
    rx = Prescription.all_objects.get(pk=result.data["id"])
    document = rx.original_document
    assert document.malware_scan_status == "NOT_SCANNED"
    assert document.metadata["malware_scanning_policy"] == "DEFERRED_BY_OPERATOR"
    assert document.metadata["malware_scanning_performed"] is False
    assert document.metadata["at_rest_encryption"]["key_id"] == "test-key"
    assert rx.legal_validation_state == "PENDING" and rx.pharmacist_verification_state == "NOT_VERIFIED"
    assert not DispensingEpisode.all_objects.exists()
    assert DocumentAccessEvent.all_objects.filter(document=document, action="UPLOAD", reason__contains="deferred").exists()
    assert result.data["documents"][0]["malware_scan_status"] == "NOT_SCANNED"
    viewed = post(intake, f"{BASE}{rx.pk}/source-document/", {"device_id": "POS-RETAIL-01", "document_id": str(document.pk)})
    assert viewed.status_code == 200 and base64.b64decode(viewed.data["content_base64"]) == PNG


def test_priced_order_must_match_prescribed_units_and_remaining_quantity(intake):
    from rest_framework.exceptions import ValidationError
    rx = Prescription.all_objects.get(pk=post(intake).data["id"])
    customer = Customer.all_objects.create(tenant=intake["tenant"], customer_number="RX-CUSTOMER", legal_name="Demo customer", customer_type="INDIVIDUAL")
    order = SalesOrder.all_objects.create(tenant=intake["tenant"], branch=intake["branch"], customer=customer, order_number="RX-ORDER", status="APPROVED", total=250)
    with pytest.raises(ValidationError, match="no approved lines"):
        PosPrescriptionIntakeViewSet.validate_order(rx, order)
    line = SalesOrderLine.all_objects.create(tenant=intake["tenant"], sales_order=order, sku=intake["sku"], unit="pack", requested_quantity=2, approved_quantity=2, line_total=250)
    PosPrescriptionIntakeViewSet.validate_order(rx, order)
    line.requested_quantity = Decimal("3")
    line.approved_quantity = Decimal("3")
    line.save()
    with pytest.raises(ValidationError, match="remaining prescribed quantity"):
        PosPrescriptionIntakeViewSet.validate_order(rx, order)
    line.approved_quantity = Decimal("2")
    line.unit = "tablet"
    line.save()
    with pytest.raises(ValidationError, match="authorised units"):
        PosPrescriptionIntakeViewSet.validate_order(rx, order)


def test_connector_configuration_errors_do_not_expose_secrets(intake, monkeypatch):
    class BrokenAdapter:
        def __init__(self, **kwargs):
            raise RuntimeError("private-token-and-source-url")
    monkeypatch.setitem(FEED_ADAPTERS, "BROKEN", BrokenAdapter)
    monkeypatch.setenv("TIBATRACE_RX_CONNECTIONS", json.dumps({str(intake["tenant"].pk): {"DHA": {
        "enabled": True, "validated": True, "adapter_code": "BROKEN", "patient_map": {"p": "x"}, "prescriber_map": {"p": "x"}, "product_map": {"p": "x"}}}}))
    result = post(intake, f"{BASE}import/", {"device_id": "POS-RETAIL-01", "idempotency_key": "feed-command", "provider": "DHA", "reference": "RX-1"})
    assert result.status_code == 400 and "private-token" not in str(result.data)


@pytest.mark.parametrize("invalid", [{"outcome": []}, {"notes": {}}, {"operation": "approve_everything"}])
def test_malformed_review_commands_are_rejected_without_advancing_rx(intake, invalid):
    created = post(intake)
    command = {"device_id": "POS-RETAIL-01", "operation": "review", **invalid}
    result = post(intake, f"{BASE}{created.data['id']}/progress/", command)
    assert result.status_code == 400
    rx = Prescription.all_objects.get(pk=created.data["id"])
    assert rx.clinical_review_state == "NOT_STARTED" and rx.pharmacist_verification_state == "NOT_VERIFIED"
