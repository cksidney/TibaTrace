"""What the POS is told about the patient at the counter.

The dispensing queue endpoint used to send `patient` and `prescription` as bare
ids and nothing else. The till needs a name, a number, a date of birth, a
prescriber and the patient's cover to show, so it filled all of them from a
hardcoded demo patient -- Grace Kamau, DEMO-PAT-1, FEMALE, 1985-05-12, SHA /
Jubilee Health, MEM-889012, Dr. David Ochieng -- and displayed that same
fictional person for every episode.

An operator checking a supply against a name and date of birth that are not the
patient's is the specific error this screen exists to prevent, so these tests
assert the payload carries the real record, and that when a record is absent the
field is null rather than a plausible substitute.

The allergy tag is the sharpest case: the markup asserted "Penicillin Conflict
Reported" for everyone. A warning shown on every patient is one staff learn to
scroll past, which is precisely when a real conflict is dispensed through.
"""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.insurance.models import (
    InsuranceCoverage,
    InsuranceMember,
    Insurer,
    InsurerPlan,
    InsurerScheme,
)
from apps.inventory.models import InventoryLocation
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient, PatientAllergy
from apps.practitioners.models import Practitioner
from apps.prescription.models import DispensingEpisode, Prescription
from apps.tenancy.models import Tenant

PASSWORD = "pos-identity-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    """The sign-in endpoint is throttled, and every test here signs in.

    Without this the later tests fail with 429 and the failure looks like a
    broken assertion rather than a shared counter.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Counter Tenant", slug="counter-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-C", name="Group")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-C", name="Branch"
    )
    user = User.objects.create_user(
        username="counter-user", password=PASSWORD, tenant=tenant
    )
    patient = Patient.all_objects.create(
        tenant=tenant, internal_reference_id="INT-REAL-77",
        patient_number="PAT-REAL-77", first_name="Amina", last_name="Wanjiru",
        date_of_birth=date(1991, 3, 14), sex="FEMALE",
    )
    practitioner = Practitioner.all_objects.create(
        tenant=tenant, first_name="Joseph", last_name="Mwangi",
        registration_number="PRAC-9001", profession="DOCTOR",
    )
    prescription = Prescription.all_objects.create(
        tenant=tenant, patient=patient, practitioner=practitioner,
        organization=org, location=branch, prescription_number="RX-REAL-4242",
        prescription_date=date.today(),
    )
    dispensary = InventoryLocation.all_objects.create(
        tenant=tenant, branch=branch, location_code="DISP-1", name="Dispensary",
        location_type=InventoryLocation.LocationType.DISPENSARY,
    )
    pharmacist = User.objects.create_user(
        username="counter-rph", password=PASSWORD, tenant=tenant
    )
    episode = DispensingEpisode.all_objects.create(
        tenant=tenant, prescription=prescription, patient=patient, branch=branch,
        pharmacy_location=dispensary, pharmacist=pharmacist,
        dispensing_number="DISP-REAL-1", idempotency_key="DISP-REAL-1-KEY",
    )
    return {
        "tenant": tenant, "user": user, "patient": patient,
        "practitioner": practitioner, "prescription": prescription,
        "episode": episode,
    }


def episode_payload(world):
    client = APIClient()
    signed_in = client.post(
        "/api/identity/session/",
        {"username": "counter-user", "password": PASSWORD},
        format="json",
    )
    assert signed_in.status_code == 200, signed_in.content
    response = client.get("/api/pos/dispensing/episodes/queue/")
    assert response.status_code == 200, response.content
    body = response.json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    assert rows, "The queue is empty for a tenant that has an episode."
    return rows[0]


# ─── the identity on the screen is the patient's ─────────────────────────────


class TestPatientIdentity:
    def test_the_payload_carries_the_real_patient(self, world):
        row = episode_payload(world)
        assert row["patient_name"] == "Amina Wanjiru"
        assert row["patient_number"] == "PAT-REAL-77"
        assert row["patient_sex"] == "FEMALE"
        assert row["patient_date_of_birth"] == "1991-03-14"

    def test_the_payload_carries_the_real_prescription_and_prescriber(self, world):
        row = episode_payload(world)
        assert row["prescription_number"] == "RX-REAL-4242"
        assert row["prescriber_name"] == "Joseph Mwangi"

    def test_no_demo_identity_appears_anywhere_in_the_payload(self, world):
        """The specific strings the till used to invent.

        Named rather than described, because the failure was not "a placeholder
        was shown" but "this exact person was shown instead of the patient".
        """
        row = episode_payload(world)
        blob = str(row)
        for invented in (
            "Grace Kamau", "DEMO-PAT-1", "1985-05-12", "DEMO-RX-8001",
            "Dr. David Ochieng", "SHA / Jubilee Health", "MEM-889012",
            "Standard Comprehensive", "Penicillin Conflict Reported",
        ):
            assert invented not in blob, f"{invented!r} is being sent to the till."


class TestAbsenceIsNull:
    """Missing data must arrive as null so the client can say "not recorded"."""

    def test_a_patient_without_a_date_of_birth_sends_null(self, world):
        world["patient"].date_of_birth = None
        world["patient"].save(update_fields=["date_of_birth"])
        assert episode_payload(world)["patient_date_of_birth"] is None

    def test_the_professional_name_is_preferred_when_recorded(self, world):
        # Practitioners are registered under a professional name that is not
        # always first + last; the prescriber shown must match the prescription.
        world["practitioner"].professional_name = "Dr J. Mwangi, MBChB"
        world["practitioner"].save(update_fields=["professional_name"])
        assert episode_payload(world)["prescriber_name"] == "Dr J. Mwangi, MBChB"

    def test_a_patient_with_no_cover_sends_null_rather_than_an_insurer(self, world):
        # The old client printed "SHA / Jubilee Health" here, naming a payer for
        # a patient who has none.
        row = episode_payload(world)
        assert row["insurer_name"] is None
        assert row["scheme_name"] is None
        assert row["membership_number"] is None


# ─── cover ───────────────────────────────────────────────────────────────────


def give_cover(world, *, valid_from=None, valid_to=None, status=None):
    insurer = Insurer.all_objects.create(
        tenant=world["tenant"], code="INS-1", name="Britam Health"
    )
    scheme = InsurerScheme.all_objects.create(
        tenant=world["tenant"], insurer=insurer, code="SCH-1", name="Corporate Plus"
    )
    plan = InsurerPlan.all_objects.create(
        tenant=world["tenant"], scheme=scheme, code="PLN-1", name="Gold"
    )
    member = InsuranceMember.all_objects.create(
        tenant=world["tenant"], membership_number="MBR-55512",
        principal_name="Amina Wanjiru",
    )
    return InsuranceCoverage.all_objects.create(
        tenant=world["tenant"], patient=world["patient"], member=member,
        scheme=scheme, plan=plan,
        status=status or InsuranceCoverage.Status.ACTIVE,
        valid_from=valid_from if valid_from is not None else date.today() - timedelta(days=30),
        valid_to=valid_to if valid_to is not None else date.today() + timedelta(days=300),
    )


class TestCover:
    def test_active_cover_is_reported(self, world):
        give_cover(world)
        row = episode_payload(world)
        assert row["insurer_name"] == "Britam Health"
        assert row["scheme_name"] == "Corporate Plus"
        assert row["membership_number"] == "MBR-55512"

    def test_expired_cover_is_not_reported(self, world):
        """Cover that lapsed is not cover.

        Showing it as live tells the cashier to bill an insurer that will refuse
        the claim, and the patient goes home without paying what they owe.
        """
        give_cover(
            world,
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=1),
        )
        assert episode_payload(world)["insurer_name"] is None

    def test_suspended_cover_is_not_reported(self, world):
        give_cover(world, status=InsuranceCoverage.Status.SUSPENDED)
        assert episode_payload(world)["insurer_name"] is None


# ─── allergies ───────────────────────────────────────────────────────────────


class TestAllergies:
    def test_a_patient_with_no_allergies_sends_an_empty_list(self, world):
        # Empty is not the same as unknown, and neither is the same as a named
        # allergy. The client renders all three differently.
        assert episode_payload(world)["allergies"] == []

    def test_a_recorded_allergy_is_sent_with_its_real_name(self, world):
        PatientAllergy.all_objects.create(
            tenant=world["tenant"], patient=world["patient"],
            allergen_name="Sulfonamides", severity="HARD_STOP", reaction="Anaphylaxis",
        )
        allergies = episode_payload(world)["allergies"]
        assert len(allergies) == 1
        assert allergies[0]["allergen_name"] == "Sulfonamides"
        assert allergies[0]["severity"] == "HARD_STOP"

    def test_penicillin_is_not_reported_for_a_patient_who_has_no_such_record(self, world):
        """The exact claim the hardcoded tag made about everybody."""
        PatientAllergy.all_objects.create(
            tenant=world["tenant"], patient=world["patient"],
            allergen_name="Sulfonamides",
        )
        names = {a["allergen_name"] for a in episode_payload(world)["allergies"]}
        assert "Penicillin" not in names
        assert names == {"Sulfonamides"}

    def test_a_refuted_allergy_is_not_reported(self, world):
        # A clinician has explicitly ruled this one out; showing it is as wrong
        # as inventing one.
        PatientAllergy.all_objects.create(
            tenant=world["tenant"], patient=world["patient"],
            allergen_name="Penicillin", status="REFUTED",
        )
        assert episode_payload(world)["allergies"] == []

    def test_an_inactive_allergy_is_not_reported(self, world):
        PatientAllergy.all_objects.create(
            tenant=world["tenant"], patient=world["patient"],
            allergen_name="Aspirin", is_active=False,
        )
        assert episode_payload(world)["allergies"] == []
