import base64
import importlib.util
import json
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.documents.encryption import encrypt_document_bytes
from apps.documents.models import StoredClinicalDocument
from apps.identity.models import User
from apps.patients.models import Patient, PatientIdentifier
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)
spec = importlib.util.spec_from_file_location(
    "dpia_runtime_evidence", Path(__file__).resolve().parents[2] / "scripts" / "collect_dpia_runtime_evidence.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


@pytest.fixture
def evidence_records(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"key-private-label": base64.urlsafe_b64encode(b"k" * 32).decode()}
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID = "key-private-label"
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = False
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    tenant = Tenant.objects.create(name="PRIVATE-ORG-NAME", slug="private-org")
    actor = User.objects.create_user(username="PRIVATE-STAFF-NAME", tenant=tenant, is_staff=True)
    patient = Patient.all_objects.create(tenant=tenant, internal_reference_id="PRIVATE-PATIENT-REFERENCE", first_name="PRIVATE-PATIENT-NAME", date_of_birth=timezone.localdate().replace(year=timezone.localdate().year - 10, day=1))
    return tenant, actor, patient


def test_evidence_is_aggregate_read_only_and_redacts_unknown_values(evidence_records):
    tenant, actor, patient = evidence_records
    PatientIdentifier.all_objects.bulk_create([PatientIdentifier(tenant=tenant, patient=patient, system="private", value="PRIVATE-IDENTIFIER-VALUE")])
    StoredClinicalDocument.all_objects.create(tenant=tenant, patient=patient, uploaded_by=actor, object_key=f"tenant/{tenant.pk}/PRIVATE-OBJECT-NAME", original_name="PRIVATE-OBJECT-NAME", content_type="text/plain", size_bytes=3, hash_sha256="a" * 64, malware_scan_status="PRIVATE-MALWARE-STATUS")
    with CaptureQueriesContext(connection) as queries:
        report = collector.collect()
    serialized = json.dumps(report)
    for private in ("PRIVATE-", str(tenant.pk), str(patient.pk), "key-private-label", base64.urlsafe_b64encode(b"k" * 32).decode()):
        assert private not in serialized
    assert report["aggregate_scale"]["patients_under_18_from_recorded_dob"] == 1
    assert report["clinical_documents"]["scan_states"] == {"UNRECOGNIZED": 1}
    assert report["patient_identifiers"]["plaintext_values_present"] == 1
    assert {"MALWARE_SCAN_DEFERRED_OR_NOT_CONFIGURED", "PLAINTEXT_PATIENT_IDENTIFIERS", "PATIENT_IDENTIFIER_CIPHERTEXT_MISSING"} <= set(report["observed_control_failures"])
    assert not any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"} for query in queries)


def test_object_verification_detects_plaintext_missing_and_corrupt_without_export(evidence_records, settings):
    import hashlib

    tenant, actor, patient = evidence_records
    content = b"PRIVATE-CLINICAL-PAYLOAD"
    for kind in ("encrypted", "legacy", "corrupt", "missing"):
        key = f"tenant/{tenant.pk}/{kind}.txt"
        path = Path(settings.MEDIA_ROOT) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind != "missing":
            payload = encrypt_document_bytes(content, key_id=settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID, key=settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS[settings.DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID], associated_data=key) if kind == "encrypted" else (b"wrong" if kind == "corrupt" else content)
            path.write_bytes(payload)
        StoredClinicalDocument.all_objects.create(tenant=tenant, patient=patient, uploaded_by=actor, object_key=key, original_name=f"{kind}.txt", content_type="text/plain", size_bytes=len(content), hash_sha256=hashlib.sha256(content).hexdigest(), malware_scan_status="NOT_SCANNED")
    report = collector.collect(verify_objects=True)
    assert report["clinical_documents"]["object_checks"] == {"integrity_valid": 2, "encrypted": 1, "legacy_plaintext": 2, "integrity_invalid": 1, "missing": 1}
    assert "CLINICAL_OBJECT_VERIFICATION_GAPS" in report["observed_control_failures"]
    assert "PRIVATE-CLINICAL-PAYLOAD" not in json.dumps(report)
    assert "PRIVATE-CLINICAL-PAYLOAD" in (Path(settings.MEDIA_ROOT) / f"tenant/{tenant.pk}/legacy.txt").read_text()


def test_collector_does_not_contact_scanner_or_providers_and_never_approves(evidence_records, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("Evidence collection may not contact providers.")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    monkeypatch.setattr("apps.documents.scanning.ClamAVScanner.scan", no_network)
    monkeypatch.setattr("sys.argv", ["collect_dpia_runtime_evidence.py", "--fail-on-gaps"])
    assert collector.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["collection"]["provider_requests"] == 0
    assert report["approval_decision"] == "NOT_DETERMINED_BY_TECHNICAL_COLLECTOR"
    assert report["technical_control_status"] == "OBSERVED_GAPS"
    assert report["submission_readiness"].startswith("ACCOUNTABLE_REVIEW_REQUIRED")


def test_clean_measured_controls_still_require_manual_review(evidence_records, settings, monkeypatch, capsys):
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = True
    settings.DAWATRACE_MALWARE_SCANNER_HOST = "private-host-never-exported"
    monkeypatch.setattr("sys.argv", ["collect_dpia_runtime_evidence.py", "--fail-on-gaps"])
    exit_code = collector.main()
    report = json.loads(capsys.readouterr().out)
    # A disposable local PostgreSQL service may intentionally lack TLS. That
    # genuine transport finding must survive the test, never be hidden/mocked.
    tls_gap = connection.vendor == "postgresql" and not report["transport_configuration"]["database_tls"]["tls"]
    assert exit_code == (2 if tls_gap else 0)
    assert report["observed_control_failures"] == (["DATABASE_CONNECTION_NOT_ENCRYPTED"] if tls_gap else [])
    assert report["technical_control_status"] == ("OBSERVED_GAPS" if tls_gap else "NO_FAILURE_IN_MEASURED_CONTROLS")
    assert report["approval_decision"] == "NOT_DETERMINED_BY_TECHNICAL_COLLECTOR"
    assert report["requires_separate_assessment"]
    assert report["clinical_documents"]["scanner_live_test"] == "NOT_PERFORMED"
    assert "private-host-never-exported" not in json.dumps(report)


def test_postgres_collection_uses_server_enforced_read_only_snapshot(evidence_records, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL transaction controls.")
    original = collector._identifier_controls
    observed = []

    def inspect_snapshot(identifiers):
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            observed.append(cursor.fetchone()[0])
            cursor.execute("SHOW transaction_isolation")
            observed.append(cursor.fetchone()[0])
        return original(identifiers)

    monkeypatch.setattr(collector, "_identifier_controls", inspect_snapshot)
    assert collector.collect()["collection"]["database_read_only_enforced"] is True
    assert observed == ["on", "repeatable read"]
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        assert cursor.fetchone()[0] == "off"


def test_invalid_keyring_does_not_escape_through_evidence(evidence_records, settings):
    settings.DAWATRACE_DOCUMENT_ENCRYPTION_KEYS = {"private-label": "PRIVATE-BROKEN-KEY"}
    report = collector.collect()
    assert "CLINICAL_OBJECT_KEYRING_INVALID" in report["observed_control_failures"]
    assert "PRIVATE-BROKEN-KEY" not in json.dumps(report)


def test_identifier_key_inventory_is_secret_free_and_detects_missing_versions(evidence_records, settings):
    tenant, _, patient = evidence_records
    row = PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="private", value="PRIVATE-IDENTIFIER-VALUE")
    report = collector.collect()
    assert report["patient_identifiers"]["independent_keyrings_valid"] is True
    assert report["patient_identifiers"]["nonactive_lookup_records"] == 0
    PatientIdentifier.all_objects.filter(pk=row.pk).update(lookup_key_id="PRIVATE-RETIRED-KEY", protected_value="ttid1:PRIVATE-RETIRED-KEY:invalid")
    report = collector.collect()
    assert report["patient_identifiers"]["unknown_lookup_version_records"] == 1
    assert report["patient_identifiers"]["unknown_ciphertext_version_records"] == 1
    assert "PATIENT_IDENTIFIER_HISTORICAL_KEYS_UNAVAILABLE" in report["observed_control_failures"]
    settings.DAWATRACE_PATIENT_IDENTIFIER_KEYS = {"private-key": "PRIVATE-INVALID-KEY"}
    report = collector.collect()
    assert "IDENTIFIER_INDEPENDENT_KEYRINGS_UNAVAILABLE" in report["observed_control_failures"]
    assert "PRIVATE-" not in json.dumps(report)


def test_identifier_collector_compatibility_with_legacy_release(evidence_records, monkeypatch):
    def legacy_module(name):
        raise ModuleNotFoundError("synthetic missing module", name=name)

    monkeypatch.setattr(collector.importlib, "import_module", legacy_module)
    report = collector.collect()
    assert report["patient_identifiers"]["key_lifecycle"] == "DJANGO_SECRET_KEY_DERIVED"
    assert "IDENTIFIER_INDEPENDENT_KEYRINGS_UNAVAILABLE" in report["observed_control_failures"]


@pytest.mark.parametrize("raw,expected", [
    ('{"PRIVATE-TENANT":{"MPESA":{"enabled":true,"secret":"PRIVATE-SECRET"}}}', {"valid_json": True, "enabled_flags": 1}),
    ('{"enabled":"true"}', {"valid_json": True, "enabled_flags": 0}),
    ('[]', {"valid_json": False, "enabled_flags": 0}),
    ('not-json', {"valid_json": False, "enabled_flags": None}),
])
def test_connection_summary_retains_no_private_configuration(monkeypatch, raw, expected):
    monkeypatch.setenv("TIBATRACE_RX_CONNECTIONS", raw)
    result = collector._configured_connections("TIBATRACE_RX_CONNECTIONS")
    assert result == expected
    assert "PRIVATE" not in json.dumps(result)
