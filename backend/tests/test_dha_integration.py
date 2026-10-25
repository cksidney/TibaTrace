import copy
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from tests.authority_helpers import grant_capabilities

from apps.identity.models import User
from apps.integrations.dha_client import DhaClient, DhaError
from apps.integrations.dha_models import DhaCallback, DhaConnection, DhaExchange
from apps.integrations.dha_security import approved_url, protect, readiness, reveal
from apps.integrations.dha_workflows import create_visit, enqueue, execute, prepare
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient, PatientIdentifier
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db
BASE = "/api/nif/dha/connections/"


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("TIBATRACE_DHA_DATA_KEYS", json.dumps([Fernet.generate_key().decode()]))
    monkeypatch.setenv("DHA_TEST_ID", "client-test")
    monkeypatch.setenv("DHA_TEST_SECRET", "test-client-secret")
    monkeypatch.setenv("DHA_TEST_CALLBACK", "c" * 40)
    tenant = Tenant.objects.create(name="DHA Test", slug="dha-test")
    org = Organization.all_objects.create(tenant=tenant, code="ORG", name="Pharmacy")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="BR", name="Branch")
    actor = User.objects.create_user(username="dha-owner", tenant=tenant, is_platform_admin=True)
    config = {"base_url": "https://ilm-dev.dha.go.ke/uat-middleware/api/v1", "allowed_hosts": ["ilm-dev.dha.go.ke"],
        "client_id_ref": "DHA_TEST_ID", "client_secret_ref": "DHA_TEST_SECRET", "callback_secret_ref": "DHA_TEST_CALLBACK",
        "facility_id": "FID-TEST-1", "practitioner_map": {str(actor.pk): "PUID-TEST-1"}, "claims_enabled": True}
    connection = DhaConnection.all_objects.create(tenant=tenant, branch=branch, environment="SANDBOX", configuration=config,
        state="SANDBOX", validated_revision=1, validated_at=timezone.now())
    patient = Patient.all_objects.create(tenant=tenant, patient_number="DHA-P1", internal_reference_id="DHA-P1", first_name="Test", last_name="Patient")
    PatientIdentifier.all_objects.create(tenant=tenant, patient=patient, system="https://cr.kenya-hie.health/fhir/NamingSystem/cr-id",
        value="CR-TEST-1", verification_status="VERIFIED")
    visit = create_visit(connection, actor, patient)
    client = APIClient()
    client.force_authenticate(actor)
    client.credentials(HTTP_X_TENANT_ID=str(tenant.pk))
    return {"tenant": tenant, "actor": actor, "branch": branch, "connection": connection, "patient": patient, "visit": visit, "client": client}


def command(w, operation, payload=None, visit=True, key=None, response=None):
    row = enqueue(w["connection"], w["actor"], operation, payload or {}, key or str(uuid.uuid4()), w["visit"] if visit else None)
    with patch.object(DhaClient, "call", return_value=(response or {}, 200)):
        return execute(row)


def open_visit(w):
    command(w, "consent_request", {"visit_type": "OP"}, response={"consent_id": "C-1", "otp_record": "O-1"})
    command(w, "consent_verify", {"otp": "123456"}, response={"visit_id": "V-1", "consent_token": "private-consent"})
    w["visit"].refresh_from_db()


def test_secrets_missing_and_revision_block_activation(world, monkeypatch):
    c = world["connection"]
    assert readiness(c)["ready"]
    monkeypatch.delenv("DHA_TEST_SECRET")
    assert not readiness(c)["ready"]
    with pytest.raises(ValidationError):
        prepare(c, world["actor"], "security_labels", {})


@pytest.mark.parametrize("base", ["http://ilm-dev.dha.go.ke/api/v1", "https://evil.test/api/v1", "https://u:p@ilm-dev.dha.go.ke/api/v1", "https://ilm-dev.dha.go.ke:8443/api/v1", "https://ilm-dev.dha.go.ke/api/v1?x=1"])
def test_destination_rejected(world, base):
    with pytest.raises(ValidationError):
        approved_url({**world["connection"].configuration, "base_url": base}, "/patients")


def test_journal_is_encrypted_and_bound_to_connection(world):
    value = protect(world["connection"], {"token": "top-secret"})
    assert "top-secret" not in value
    other = copy.copy(world["connection"])
    other.pk = uuid.uuid4()
    with pytest.raises(ValidationError):
        reveal(other, value)


def test_consent_workflow_refusal_and_closure(world):
    open_visit(world)
    assert world["visit"].state == "OPEN"
    row = command(world, "visit_close", response={"otp_record": "CLOSE-OTP"})
    world["visit"].refresh_from_db()
    assert row.state == "ACCEPTED" and world["visit"].state == "CLOSING"
    with pytest.raises(ValidationError):
        prepare(world["connection"], world["actor"], "patient_records", {"resources": "MedicationRequest"}, world["visit"])
    command(world, "consent_verify", {"otp": "654321"}, response={"end_date": timezone.now().isoformat()})
    world["visit"].refresh_from_db()
    assert world["visit"].state == "CLOSED"
    assert "consent_token" not in reveal(world["connection"], world["visit"].protected_context)


def test_patient_and_practitioner_override_is_ignored(world):
    open_visit(world)
    _, _, data, _ = prepare(world["connection"], world["actor"], "patient_records",
        {"resources": "MedicationRequest", "cr_id": "FOREIGN", "practitioner_id": "FOREIGN"}, world["visit"])
    assert data["cr_id"] == "CR-TEST-1" and data["practitioner_id"] == "PUID-TEST-1"


def test_expired_consent_blocks_reads(world):
    open_visit(world)
    world["visit"].consent_expires_at = timezone.now() - timedelta(seconds=1)
    with pytest.raises(ValidationError):
        prepare(world["connection"], world["actor"], "patient_records", {"resources": "MedicationRequest"}, world["visit"])


def test_otp_removed_and_idempotency_key_immutable(world):
    command(world, "consent_request", {"visit_type": "OP"}, response={"consent_id": "C-1", "otp_record": "O-1"})
    row = command(world, "consent_verify", {"otp": "123456"}, key="otp-key-001", response={"visit_id": "V-1", "consent_token": "private-token"})
    assert "otp" not in reveal(world["connection"], row.protected_request)["payload"]
    replay = enqueue(world["connection"], world["actor"], "consent_verify", {"otp": "123456"}, "otp-key-001", world["visit"])
    assert replay.pk == row.pk
    with pytest.raises(ValidationError):
        enqueue(world["connection"], world["actor"], "consent_verify", {"otp": "654321"}, "otp-key-001", world["visit"])


def test_uncertain_mutation_is_never_implicitly_replayed(world):
    row = enqueue(world["connection"], world["actor"], "consent_request", {"visit_type": "OP"}, "uncertain-001", world["visit"])
    with patch.object(DhaClient, "call", side_effect=DhaError("TIMEOUT", uncertain=True)) as call:
        row = execute(row)
        execute(row)
    assert row.state == "UNCERTAIN" and call.call_count == 1


def test_read_retries_are_bounded_and_configuration_change_stops_delivery(world):
    row = enqueue(world["connection"], world["actor"], "security_labels", {}, "retry-key-001")
    with patch.object(DhaClient, "call", side_effect=DhaError("OUTAGE", 503, retryable=True)):
        row = execute(row)
    assert row.state == "RETRY" and row.next_attempt_at
    row.next_attempt_at = timezone.now()
    row.save()
    c = world["connection"]
    c.revision += 1
    c.save()
    with patch.object(DhaClient, "call") as call:
        row = execute(row)
    assert row.state == "FAILED" and call.call_count == 0


def test_api_tenant_isolation_and_branch_scope(world):
    foreign = Tenant.objects.create(name="Foreign", slug="foreign-dha")
    outsider = User.objects.create_user(username="outsider-dha", tenant=foreign)
    grant_capabilities(outsider, "dha.configure")
    world["client"].force_authenticate(outsider)
    world["client"].credentials(HTTP_X_TENANT_ID=str(foreign.pk))
    assert world["client"].get(BASE).json() == []
    assert world["client"].get(f"{BASE}{world['connection'].pk}/exchanges/").status_code == 404


def test_configuration_edit_disables_connection(world):
    c = world["connection"]
    response = world["client"].patch(f"{BASE}{c.pk}/", {"configuration": c.configuration}, format="json")
    assert response.status_code == 200, response.data
    c.refresh_from_db()
    assert c.state == "DISABLED" and c.revision == 2 and not readiness(c)["ready"]


def test_callback_authentication_deduplication_and_facility_binding(world):
    c = world["connection"]
    url = f"/api/nif/dha/callbacks/{c.pk}/claim/"
    payload = {"entity_type": "claim", "subject_guid": "subject-1", "from_state": "SUBMITTED_PAYER", "to_state": "APPROVED",
        "timestamp": timezone.now().isoformat(), "facility_fr_code": c.configuration["facility_id"]}
    assert world["client"].post(url, payload, format="json").status_code == 403
    for duplicate in [False, True]:
        r = world["client"].post(url, payload, format="json", HTTP_AUTHORIZATION="Bearer " + "c" * 40)
        assert r.status_code == 200, r.data
        assert r.data["duplicate"] == duplicate
    assert DhaCallback.all_objects.count() == 1
    payload["facility_fr_code"] = "FOREIGN"
    assert world["client"].post(url, payload, format="json", HTTP_AUTHORIZATION="Bearer " + "c" * 40).status_code == 400


def test_claims_cannot_use_browser_supplied_consent_or_shr_token(world):
    open_visit(world)
    with pytest.raises(ValidationError):
        prepare(world["connection"], world["actor"], "claim_submit", {"consent_token": "forged"}, world["visit"])
    command(world, "claims_visit", {"otp": "123456"}, response={"consent_token": "sha-token"})
    world["visit"].refresh_from_db()
    _, _, body, _ = prepare(world["connection"], world["actor"], "claim_submit", {"consent_token": "forged"}, world["visit"])
    assert body["consent_token"] == "sha-token"


def test_activation_requires_evidence_owner_and_current_validation(world):
    c = world["connection"]
    response = world["client"].post(f"{BASE}{c.pk}/activate/", {"evidence": {}}, format="json")
    assert response.status_code == 400
    response = world["client"].post(f"{BASE}{c.pk}/activate/", {"evidence": {k: "evidence-case-001" for k in
        ("sandbox_uat", "security_review", "system_dpia", "facility_approval")}}, format="json")
    assert response.status_code == 200, response.data


def test_unexpected_success_body_never_opens_consent(world):
    row = command(world, "consent_request", {"visit_type": "OP"}, response={"message": "queued"})
    world["visit"].refresh_from_db()
    assert row.state == "UNCERTAIN" and world["visit"].state == "PENDING"


def test_revoked_actor_and_suspended_connection_stop_queued_commands(world):
    row = enqueue(world["connection"], world["actor"], "security_labels", {}, "deactivate-actor-001")
    world["actor"].is_active = False
    world["actor"].save(update_fields=["is_active"])
    with patch.object(DhaClient, "call") as call:
        assert execute(row).state == "FAILED"
    assert call.call_count == 0
    world["actor"].is_active = True
    world["actor"].save(update_fields=["is_active"])
    row = enqueue(world["connection"], world["actor"], "security_labels", {}, "suspend-connection-001")
    DhaConnection.all_objects.filter(pk=world["connection"].pk).update(state="SUSPENDED")
    with patch.object(DhaClient, "call") as call:
        assert execute(row).state == "FAILED"
    assert call.call_count == 0


def test_old_consent_cannot_reopen_a_closed_visit(world):
    open_visit(world)
    command(world, "visit_close", response={"end_date": timezone.now().isoformat()})
    world["visit"].refresh_from_db()
    with pytest.raises(ValidationError):
        enqueue(world["connection"], world["actor"], "consent_status", {}, "closed-status-001", world["visit"])


def test_same_national_rx_has_one_source_reference_across_visits(world):
    from apps.integrations.dha_rx import canonical_source_reference
    first = canonical_source_reference(world["tenant"], world["branch"], "DHA", f"{uuid.uuid4()}:rx-123")
    second = canonical_source_reference(world["tenant"], world["branch"], "DHA", f"{uuid.uuid4()}:rx-123")
    assert first == second == "rx-123"


def test_remittances_require_an_assigned_contract_and_force_branch_scope(world):
    with pytest.raises(ValidationError, match="confirm this remittance"):
        prepare(world["connection"], world["actor"], "remittances", {})
    world["connection"].configuration["remittance_paths"] = {"remittances": "/assigned/remittances"}
    _, path, data, _ = prepare(world["connection"], world["actor"], "remittances", {"facility_id": "FOREIGN"})
    assert path == "/assigned/remittances" and data["facility_id"] == "FID-TEST-1"


def test_production_cannot_use_sandbox_without_a_server_environment_binding(world):
    world["connection"].environment = "PRODUCTION"
    assert any("production API base" in b for b in readiness(world["connection"])["blockers"])


@pytest.mark.parametrize("route,payload", [("", {"branch": "not-a-uuid"}), ("visits/", {"patient": "not-a-uuid"}),
    ("confirm-bundle/", {"exchange": "not-a-uuid"})])
def test_malformed_local_identifiers_are_validation_errors(world, route, payload):
    url = BASE if not route else f"{BASE}{world['connection'].pk}/{route}"
    assert world["client"].post(url, payload, format="json").status_code == 400


def test_callback_rejects_malformed_bodies_and_invalid_calendar_dates(world):
    url = f"/api/nif/dha/callbacks/{world['connection'].pk}/claim/"
    headers = {"HTTP_AUTHORIZATION": "Bearer " + "c" * 40}
    assert world["client"].post(url, [], format="json", **headers).status_code == 400
    payload = {"entity_type": "claim", "subject_guid": "subject-1", "from_state": "A", "to_state": "B",
        "timestamp": "2026-13-01T00:00:00+03:00", "facility_fr_code": "FID-TEST-1"}
    assert world["client"].post(url, payload, format="json", **headers).status_code == 400


def test_worker_recovers_reads_without_replaying_interrupted_mutations(world):
    from django.core.management import call_command
    read = enqueue(world["connection"], world["actor"], "security_labels", {}, "worker-read-test")
    mutation = enqueue(world["connection"], world["actor"], "consent_request", {"visit_type": "OP"}, "worker-mutation-test", world["visit"])
    DhaExchange.all_objects.filter(pk__in=[read.pk, mutation.pk]).update(state="IN_FLIGHT", attempts=1,
        lease_expires_at=timezone.now() - timedelta(minutes=1))
    with patch.object(DhaClient, "call", return_value=({}, 200)) as call:
        call_command("process_dha_exchanges", limit=10)
    read.refresh_from_db()
    mutation.refresh_from_db()
    assert read.state == "CONFIRMED" and mutation.state == "UNCERTAIN" and call.call_count == 1


@pytest.mark.parametrize("required,status,allowed", [(True, "CLEAN", True), (True, "NOT_SCANNED", False),
    (False, "NOT_SCANNED", True), (False, "INFECTED", False), (False, "ERROR", False), (False, "PENDING", False)])
def test_document_exports_respect_scan_policy_without_relaxing_known_failures(world, settings, required, status, allowed):
    from apps.documents.models import StoredClinicalDocument
    from apps.integrations.dha_documents import documents_for_exchange
    settings.DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED = required
    document = StoredClinicalDocument.all_objects.create(tenant=world["tenant"], patient=world["patient"], uploaded_by=world["actor"],
        object_key=f"tenant/{world['tenant'].pk}/test-rx.pdf", original_name="rx.pdf", content_type="application/pdf",
        size_bytes=100, hash_sha256="a" * 64, malware_scan_status=status)
    def check():
        return documents_for_exchange(world["connection"], world["visit"], world["actor"], [{"document_id": str(document.pk)}])
    if allowed:
        check()
    else:
        with pytest.raises(ValidationError):
            check()
    document.refresh_from_db()
    assert document.malware_scan_status == status


def test_disabled_connections_are_not_activated_by_scheduled_maintenance(world, settings):
    from apps.integrations.tasks import process_dha_exchanges
    DhaConnection.all_objects.filter(pk=world["connection"].pk).update(state="DISABLED")
    with patch.object(DhaClient, "call") as call:
        assert process_dha_exchanges.run() == {"completed": True}
    world["connection"].refresh_from_db()
    assert world["connection"].state == "DISABLED" and call.call_count == 0
    assert settings.CELERY_BEAT_SCHEDULE["dha-exchange-retries"]["schedule"] == 60.0
