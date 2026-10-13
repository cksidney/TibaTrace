
# ruff: noqa: F811
import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from tests.test_pos_enterprise_dispensing import domain, grant, make_clinically_ready, setup_domain  # noqa: F401

from apps.audit.models import AuditEvent
from apps.identity.models import User
from apps.patients.models import PatientAllergy
from apps.prescription.models import DispensingCheck, MedicineSupply
from apps.prescription.services.clinical_dispensing import PrescriptionLifecycleService

pytestmark = pytest.mark.django_db


def client(user):
    api = APIClient()
    api.force_login(user)
    return api


@pytest.mark.parametrize("state", ["PAID", "READY_FOR_COLLECTION", "PARTIALLY_SUPPLIED", "SUPPLIED", "CLOSED", "REVERSED", "RETURNED"])
def test_generic_transition_cannot_create_a_business_fact(domain, state):
    episode = domain["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.save()
    response = client(domain["pharmacist"]).post(
        f"/api/pos/dispensing/episodes/{episode.pk}/transition-state/",
        {"new_status": state}, format="json",
    )
    assert response.status_code == 400
    episode.refresh_from_db()
    assert episode.status == "READY_FOR_SUPPLY"
    assert not MedicineSupply.all_objects.filter(episode=episode).exists()


@pytest.mark.parametrize("path", ["episodes/queue/", "shifts/", "devices/", "print-jobs/"])
def test_unauthorised_identity_cannot_browse_pos_records(domain, path):
    user = User.objects.create_user(username="no-pos-role", tenant=domain["tenant"])
    response = client(user).get(f"/api/pos/dispensing/{path}")
    assert response.status_code == 403


def test_cashier_gets_minimum_necessary_profile_and_checker_access_is_audited(domain):
    PatientAllergy.all_objects.create(
        tenant=domain["tenant"], patient=domain["patient"], allergen_name="Penicillin",
        reaction="Severe reaction test", severity="HARD_STOP",
    )
    episode = domain["episode"]
    episode.notes = "Confidential clinical note"
    episode.save()
    path = f"/api/pos/dispensing/episodes/{episode.pk}/"
    cashier_response = client(domain["cashier"]).get(path)
    assert cashier_response.status_code == 200
    cashier = cashier_response.json()
    assert cashier["patient_name"] == "John Doe"
    assert cashier["patient_number"] == "PAT-001"
    assert cashier["patient_date_of_birth"] is None
    assert cashier["allergies"] == []
    assert cashier["notes"] is None
    assert cashier["clinical_details_visible"] is False
    assert cashier["lines"][0]["dosage_label_instructions"] == ""
    assert cashier["lines"][0]["supplied_medicine_name"] == domain["sku"].display_name
    pharmacist_response = client(domain["pharmacist"]).get(path)
    assert pharmacist_response.status_code == 200
    pharmacist = pharmacist_response.json()
    assert pharmacist["allergies"][0]["reaction"] == "Severe reaction test"
    assert pharmacist["clinical_details_visible"] is True
    assert AuditEvent.all_objects.filter(
        tenant=domain["tenant"], actor=domain["pharmacist"], action="POS_CLINICAL_PROFILE_VIEWED",
        object_id=str(episode.pk),
    ).exists()


def test_explicit_branch_assignment_scopes_queue_and_detail(domain):
    user = domain["pharmacist"]
    user.metadata = {"branch_ids": []}
    user.save()
    api = client(user)
    assert api.get("/api/pos/dispensing/episodes/queue/").json() == []
    assert api.get(f"/api/pos/dispensing/episodes/{domain['episode'].pk}/").status_code == 404


def test_native_prepare_and_check_use_canonical_independent_services(domain):
    make_clinically_ready(domain)
    episode = domain["episode"]
    DispensingCheck.all_objects.filter(episode=episode).delete()
    path = f"/api/pos/dispensing/episodes/{episode.pk}/"
    api = client(domain["pharmacist"])
    prepared = api.post(f"{path}prepare/", {}, format="json")
    assert prepared.status_code == 200, prepared.data
    episode.refresh_from_db()
    assert episode.status == "CHECKING"
    checklist = {name: True for name in (
        "patient", "medicine", "strength", "dosage_form", "quantity", "batch", "expiry",
        "instructions", "warnings", "package_integrity",
    )}
    assert api.post(f"{path}check/", {"checklist": checklist}, format="json").status_code == 400
    independent = client(domain["witness"])
    assert independent.post(f"{path}check/", {"checklist": {}}, format="json").status_code == 400
    checked = independent.post(f"{path}check/", {"checklist": checklist}, format="json")
    assert checked.status_code == 200, checked.data
    assert DispensingCheck.all_objects.get(episode=episode).checked_by_id == domain["witness"].pk
    episode.refresh_from_db()
    assert episode.status == "READY_FOR_SUPPLY"


def test_paid_prescription_cannot_be_cancelled_as_unpaid(domain):
    episode = domain["episode"]
    episode.payment_state = "PAID"
    episode.save()
    grant(domain["pharmacist"], domain["tenant"], ["prescriptions.intake"], "INTAKE")
    with pytest.raises(ValidationError, match="reversal/return"):
        PrescriptionLifecycleService.cancel(
            prescription=domain["rx"], actor=domain["pharmacist"], reason="Wrong sale",
        )
    episode.refresh_from_db()
    assert episode.payment_state == "PAID"


def test_browser_till_is_installation_only():
    response = APIClient().get("/pos/")
    assert response.status_code == 200
    assert b"browser till has been retired" in response.content
    assert b"pos/js/pos.js" not in response.content


def test_hq_intake_options_and_actual_prescription_creation_do_not_claim_verification(domain):
    user = domain["pharmacist"]
    grant(user, domain["tenant"], ["prescriptions.intake", "prescriptions.read"], "INTAKE")
    api = client(user)
    options = api.get("/api/prescriptions/intake-options/")
    assert options.status_code == 200, options.data
    assert options.json()["patients"][0]["name"] == "John Doe"
    assert "date_of_birth" not in options.json()["patients"][0]
    received = api.post("/api/prescriptions/", {
        "patient": str(domain["patient"].pk), "practitioner": str(domain["practitioner"].pk),
        "organization": str(domain["branch"].organization_id), "location": str(domain["branch"].pk),
        "prescription_number": "MANUAL-RX-001", "external_prescription_reference": "MANUAL-RX-001",
        "prescription_date": "2026-10-13", "prescription_type": "ACUTE", "source_channel": "PAPER",
        "items": [{"prescribed_sku": str(domain["sku"].pk), "medication_name": domain["sku"].display_name,
                   "quantity": "3", "unit": "TABLET", "dosage_instruction": "Take one daily"}],
    }, format="json")
    assert received.status_code == 201, received.data
    assert received.json()["status"] == "RECEIVED"
    assert received.json()["pharmacist_verification_state"] == "NOT_VERIFIED"
    assert api.post("/api/dispensing/episodes/", {
        "prescription_id": received.json()["id"], "branch_id": str(domain["branch"].pk),
        "pharmacy_location_id": str(domain["wh"].pk), "payment_state": "PENDING", "idempotency_key": "unverified-episode",
    }, format="json").status_code == 400


def test_public_episode_creation_does_not_turn_missing_price_into_free_supply(domain):
    make_clinically_ready(domain)
    actor = domain["pharmacist"]
    grant(actor, domain["tenant"], ["dispensing.reserve"], "ORIGINATION")
    api = client(actor)
    body = {"prescription_id": str(domain["rx"].pk), "branch_id": str(domain["branch"].pk),
            "pharmacy_location_id": str(domain["wh"].pk), "idempotency_key": "public-no-price"}
    response = api.post("/api/dispensing/episodes/", body, format="json")
    assert response.status_code == 201, response.data
    assert response.json()["payment_state"] == "PENDING"
    waived = api.post("/api/dispensing/episodes/", {**body, "idempotency_key": "unauthorised-waiver", "payment_state": "WAIVED", "notes": "Try waived"}, format="json")
    assert waived.status_code == 403


def test_uncompleted_topics_cannot_record_counselling(domain):
    make_clinically_ready(domain)
    episode = domain["episode"]
    episode.status = "READY_FOR_SUPPLY"
    episode.save()
    path = f"/api/pos/dispensing/episodes/{episode.pk}/record-counselling/"
    api = client(domain["pharmacist"])
    assert api.post(path, {}, format="json").status_code == 400
    topics = {key: True for key in (
        "medicine_explained", "dosage_explained", "storage_explained", "side_effects_discussed",
        "interaction_advice_given", "patient_acknowledged",
    )}
    topics["patient_acknowledged"] = False
    assert api.post(path, topics, format="json").status_code == 400


def test_paid_final_check_makes_payment_reachable_and_cash_settlement_then_collection(domain):
    make_clinically_ready(domain)
    episode = domain["episode"]
    DispensingCheck.all_objects.filter(episode=episode).delete()
    episode.payment_state = "PENDING"
    episode.save()
    path = f"/api/pos/dispensing/episodes/{episode.pk}/"
    assert client(domain["pharmacist"]).post(f"{path}prepare/", {}, format="json").status_code == 200
    checklist = {name: True for name in (
        "patient", "medicine", "strength", "dosage_form", "quantity", "batch", "expiry",
        "instructions", "warnings", "package_integrity",
    )}
    assert client(domain["witness"]).post(f"{path}check/", {"checklist": checklist}, format="json").status_code == 200
    episode.refresh_from_db()
    assert episode.status == "READY_FOR_PAYMENT"
    payment = client(domain["cashier"]).post(f"{path}process-payment/", {
        "tender_type": "CASH", "paid_amount": "150.00", "idempotency_key": "canonical-cash",
        "device_id": domain["device_id"],
    }, format="json")
    assert payment.status_code == 200, payment.data
    episode.refresh_from_db()
    assert episode.status == "PAID"
    collection = client(domain["pharmacist"]).post(f"{path}confirm-collection/", {
        "collector_name": "John Doe", "idempotency_key": "canonical-supply",
    }, format="json")
    assert collection.status_code == 200, collection.data
    assert MedicineSupply.all_objects.filter(episode=episode).count() == 1
