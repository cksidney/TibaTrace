# ruff: noqa: F811 -- imported shared pytest fixtures are injected by name.
import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from tests.authority_helpers import grant_capabilities
from tests.test_dha_integration import open_visit, world  # noqa: F401
from tests.test_pos_enterprise_dispensing import (
    advance_to_ready_for_supply,
    make_clinically_ready,
    setup_domain,  # noqa: F401
)
from tests.test_pos_enterprise_dispensing import (
    domain as clinical_domain,  # noqa: F401
)

from apps.integrations.dha_bundles import supply_bundle
from apps.integrations.dha_client import DhaClient
from apps.integrations.dha_models import DhaConnection, DhaVisit
from apps.integrations.dha_rx import DhaPrescriptionFeed
from apps.integrations.dha_security import protect
from apps.integrations.dha_workflows import enqueue, execute, validate_bundle
from apps.prescription.pos_dispensing_services import PosCollectionService

pytestmark = pytest.mark.django_db
LABELS = [{"system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality", "code": "N"}]


def test_real_supply_builds_fhir_and_readback_requires_all_records(world, clinical_domain):
    d = clinical_domain
    actor = grant_capabilities(d["pharmacist"], "dha.exchange", "dha.configure")
    d["rx"].prescription_date = timezone.localdate()
    d["rx"].save(update_fields=["prescription_date"])
    make_clinically_ready(d)
    episode = advance_to_ready_for_supply(d)
    supply = PosCollectionService.confirm_collection(episode=episode, collector_name="Test Patient", collector_id_number="ID-TEST",
        collector_phone="0712345678", collector_relationship="SELF", collection_proof_type="SIGNATURE", signature_ref="SIG-TEST",
        actor=actor, idempotency_key="dha-supply-test")
    connection = DhaConnection.all_objects.create(tenant=d["tenant"], branch=d["branch"], environment="SANDBOX", state="SANDBOX",
        validated_revision=1, configuration={**world["connection"].configuration,
            "practitioner_map": {str(actor.pk): "PUID-TEST-1"}, "prescriber_map": {"PUID-PRESCRIBER": str(d["practitioner"].pk)},
            "product_map": {"https://example.test/drugs|PARA500": str(d["sku"].pk)},
            "unit_map": {"TABLET": {"system": "http://unitsofmeasure.org", "code": "{tbl}"}}})
    context = {"cr_id": "CR-CLINICAL-1", "practitioner_id": "PUID-TEST-1", "visit_id": "national-visit-1", "consent_token": "protected-token"}
    visit = DhaVisit.all_objects.create(tenant=d["tenant"], connection=connection, patient=d["patient"], actor=actor,
        state="OPEN", consent_expires_at=timezone.now() + timedelta(minutes=5), protected_context=protect(connection, context))
    bundle = supply_bundle(connection, visit, context, supply.pk, LABELS)
    validate_bundle(bundle, context)
    assert {e["resource"]["resourceType"] for e in bundle["entry"]} == {"Encounter", "MedicationRequest", "MedicationDispense"}
    command = enqueue(connection, actor, "bundle_submit", {"supply_id": str(supply.pk), "security_labels": LABELS}, "supply-bundle-test", visit)
    def acknowledgement(op, path, payload, **kwargs):
        return {"mediator_id": payload["id"], "status": "success"}, 200
    with patch.object(DhaClient, "call", side_effect=acknowledgement):
        command = execute(command)
    assert command.state == "ACCEPTED"  # Receipt does not prove persistence.
    client = APIClient()
    client.force_authenticate(actor)
    client.credentials(HTTP_X_TENANT_ID=str(d["tenant"].pk))
    url = f"/api/nif/dha/connections/{connection.pk}/confirm-bundle/"
    with patch.object(DhaClient, "call", return_value=({"resourceType": "Bundle", "type": "searchset", "entry": []}, 200)):
        response = client.post(url, {"exchange": str(command.pk)}, format="json")
    assert response.status_code == 202, response.data
    by_id = {e["resource"]["id"]: e for e in bundle["entry"]}
    def readback(op, path, payload, **kwargs):
        return {"resourceType": "Bundle", "type": "searchset", "entry": [by_id[payload["_id"]]]}, 200
    with patch.object(DhaClient, "call", side_effect=readback):
        response = client.post(url, {"exchange": str(command.pk)}, format="json")
    assert response.status_code == 200 and response.data["state"] == "CONFIRMED", response.data
    altered = copy.deepcopy(bundle)
    altered["entry"][0]["resource"]["subject"]["reference"] = "Patient/FOREIGN"
    with pytest.raises(ValidationError):
        validate_bundle(altered, context)


def test_prescription_intake_reconciles_prior_national_fills(world, clinical_domain):
    # Use an actual governed SKU; no source-provided local identifier is trusted.
    d = clinical_domain
    d["sku"].status = "ACTIVE"
    d["sku"].save(update_fields=["status"])
    actor = grant_capabilities(d["pharmacist"], "dha.exchange")
    connection = DhaConnection.all_objects.create(tenant=d["tenant"], branch=d["branch"], environment="SANDBOX", state="SANDBOX",
        validated_revision=1, configuration={**world["connection"].configuration, "practitioner_map": {str(actor.pk): "PUID-TEST-1"},
            "prescriber_map": {"PUID-PRESCRIBER": str(d["practitioner"].pk)}, "product_map": {"https://example.test/drugs|PARA500": str(d["sku"].pk)}})
    visit = DhaVisit.all_objects.create(tenant=d["tenant"], connection=connection, patient=d["patient"], actor=actor, state="OPEN",
        consent_expires_at=timezone.now() + timedelta(minutes=5), protected_context=protect(connection,
            {"cr_id": "CR-TEST-1", "practitioner_id": "PUID-TEST-1", "consent_token": "consented", "visit_id": "national-visit"}))
    rx = {"resourceType": "MedicationRequest", "id": "rx-1", "status": "active", "intent": "order",
        "subject": {"reference": "Patient/CR-TEST-1"}, "requester": {"reference": "Practitioner/PUID-PRESCRIBER"},
        "medicationCodeableConcept": {"coding": [{"system": "https://example.test/drugs", "code": "PARA500"}]},
        "authoredOn": "2026-10-20", "dispenseRequest": {"quantity": {"value": 30, "unit": "TABLET"}},
        "dosageInstruction": [{"text": "One tablet as prescribed"}]}
    fill = {"resourceType": "MedicationDispense", "id": "old-fill-1", "status": "completed", "authorizingPrescription": [{"reference": "MedicationRequest/rx-1"}], "quantity": {"value": 10, "unit": "TABLET"}}
    calls = []
    def response(op, path, payload, **kwargs):
        calls.append(payload)
        resources = [rx] if payload["resources"] == "MedicationRequest" else [fill]
        return {"resourceType": "Bundle", "type": "searchset", "entry": [{"resource": r} for r in resources]}, 200
    with patch.object(DhaClient, "call", side_effect=response):
        received = DhaPrescriptionFeed(connection, actor).fetch_prescription(f"{visit.pk}:rx-1")
    assert received["items"][0]["quantity"] == "20"
    assert [c["resources"] for c in calls] == ["MedicationRequest", "MedicationDispense"]
