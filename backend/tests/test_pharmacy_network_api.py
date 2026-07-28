"""The pharmacy network API.

Read-only over the collection, with every state change behind a named service
action. There is no generic PATCH on status on purpose -- the module exists so
that a pharmacy's state moves only through rules that check a licence and record
who decided.

The old surface at /api/tenancy/tenants/ is asserted read-only here. It used to
create a tenant straight into ACTIVE with no licence, no organization, no branch
and nobody able to sign in, and its suspend action stopped nothing.
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.pharmacy_network.services import PharmacyOnboardingService
from apps.tenancy.models import Tenant

PASSWORD = "network-api-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        username="network-admin", password=PASSWORD, is_platform_admin=True
    )


@pytest.fixture
def client(admin):
    api = APIClient()
    assert api.post(
        "/api/identity/session/",
        {"username": "network-admin", "password": PASSWORD}, format="json",
    ).status_code == 200
    return api


def registration_payload(**overrides):
    payload = {
        "name": "Westlands Pharmacy",
        "slug": "westlands",
        "legal_name": "Westlands Pharmaceuticals Ltd",
        "ppb_premises_licence_number": "PPB/PREM/2026/0442",
        "ppb_licence_expiry": (timezone.localdate() + timedelta(days=200)).isoformat(),
        "superintendent_name": "Wanjiru Kamau",
    }
    payload.update(overrides)
    return payload


class TestRegistration:
    def test_a_registered_pharmacy_starts_as_a_prospect(self, client):
        response = client.post(
            "/api/pharmacy-network/pharmacies/", registration_payload(), format="json"
        )
        assert response.status_code == 201
        assert response.json()["status"] == Tenant.STATUS_PROSPECT

    def test_the_response_says_what_may_happen_next(self, client):
        """The client renders exactly these, so a button never offers a
        transition the service will refuse."""
        body = client.post(
            "/api/pharmacy-network/pharmacies/", registration_payload(), format="json"
        ).json()
        assert body["available_transitions"] == ["ONBOARDING", "TERMINATED"]

    def test_a_duplicate_slug_is_refused(self, client):
        client.post("/api/pharmacy-network/pharmacies/", registration_payload(), format="json")
        second = client.post(
            "/api/pharmacy-network/pharmacies/", registration_payload(), format="json"
        )
        assert second.status_code == 400
        assert "slug" in second.json()

    def test_an_operator_cannot_register_a_pharmacy(self, db):
        tenant = Tenant.objects.create(name="Someone Else", slug="someone-else")
        User.objects.create_user(username="op", password=PASSWORD, tenant=tenant)
        api = APIClient()
        api.post(
            "/api/identity/session/",
            {"username": "op", "password": PASSWORD}, format="json",
        )
        response = api.post(
            "/api/pharmacy-network/pharmacies/", registration_payload(), format="json"
        )
        assert response.status_code == 403


class TestTheOnboardingRoute:
    def test_a_pharmacy_reaches_trading_through_the_gates(self, client):
        created = client.post(
            "/api/pharmacy-network/pharmacies/", registration_payload(), format="json"
        ).json()
        pk = created["id"]

        onboarded = client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/begin-onboarding/",
            {
                "organization_name": "Westlands Group", "organization_code": "WLG",
                "branch_name": "Westlands Main", "branch_code": "WL-MAIN",
            },
            format="json",
        )
        assert onboarded.status_code == 200
        assert onboarded.json()["status"] == Tenant.STATUS_ONBOARDING
        # Provisioning is the point: a tenant with no branch cannot dispense.
        assert onboarded.json()["branch_count"] == 1

        activated = client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/activate/", {}, format="json"
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == Tenant.STATUS_ACTIVE

    def test_activation_without_a_licence_is_refused_with_the_reason(self, client):
        created = client.post(
            "/api/pharmacy-network/pharmacies/",
            registration_payload(
                slug="unlicensed-api",
                ppb_premises_licence_number="",
                ppb_licence_expiry=None,
            ),
            format="json",
        ).json()
        pk = created["id"]
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/begin-onboarding/",
            {
                "organization_name": "Unlicensed", "organization_code": "UNA",
                "branch_name": "Main", "branch_code": "UNA-MAIN",
            },
            format="json",
        )
        response = client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/activate/", {}, format="json"
        )
        # 400 with the service's own words, not a generic failure: the operator
        # needs to know it is the licence that is missing.
        assert response.status_code == 400
        assert "premises licence" in str(response.json())

    def test_a_prospect_cannot_be_activated_directly(self, client):
        pk = client.post(
            "/api/pharmacy-network/pharmacies/",
            registration_payload(slug="skip-ahead"), format="json",
        ).json()["id"]
        response = client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/activate/", {}, format="json"
        )
        assert response.status_code == 400


class TestSuspension:
    def _live(self, client, slug="live-one"):
        pk = client.post(
            "/api/pharmacy-network/pharmacies/",
            registration_payload(slug=slug), format="json",
        ).json()["id"]
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/begin-onboarding/",
            {
                "organization_name": "Live Group", "organization_code": f"LG{slug[:3]}",
                "branch_name": "Main", "branch_code": f"LB-{slug[:5]}",
            },
            format="json",
        )
        client.post(f"/api/pharmacy-network/pharmacies/{pk}/activate/", {}, format="json")
        return pk

    def test_suspending_requires_a_reason(self, client):
        pk = self._live(client, "needs-reason")
        response = client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/suspend/", {}, format="json"
        )
        assert response.status_code == 400

    def test_a_suspension_is_recorded_with_its_reason_and_actor(self, client):
        pk = self._live(client, "recorded-api")
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/suspend/",
            {"reason": "Premises inspection pending."}, format="json",
        )
        history = client.get(f"/api/pharmacy-network/pharmacies/{pk}/lifecycle/").json()
        suspension = next(e for e in history if e["to_state"] == "SUSPENDED")
        assert suspension["reason"] == "Premises inspection pending."
        assert suspension["actor_name"] == "network-admin"

    def test_the_full_history_survives_repeated_suspensions(self, client):
        pk = self._live(client, "history-api")
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/suspend/",
            {"reason": "First."}, format="json",
        )
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/reinstate/", {}, format="json"
        )
        client.post(
            f"/api/pharmacy-network/pharmacies/{pk}/suspend/",
            {"reason": "Second."}, format="json",
        )
        history = client.get(f"/api/pharmacy-network/pharmacies/{pk}/lifecycle/").json()
        reasons = sorted(e["reason"] for e in history if e["to_state"] == "SUSPENDED")
        assert reasons == ["First.", "Second."]


class TestProfileMaintenance:
    def test_a_renewed_licence_can_be_recorded_without_a_state_change(self, client):
        """Otherwise a pharmacy would have to be suspended to do its paperwork."""
        pk = client.post(
            "/api/pharmacy-network/pharmacies/",
            registration_payload(slug="renewing"), format="json",
        ).json()["id"]
        new_expiry = (timezone.localdate() + timedelta(days=400)).isoformat()
        response = client.patch(
            f"/api/pharmacy-network/pharmacies/{pk}/profile/",
            {"ppb_licence_expiry": new_expiry}, format="json",
        )
        assert response.status_code == 200
        assert response.json()["profile"]["ppb_licence_expiry"] == new_expiry
        assert response.json()["status"] == Tenant.STATUS_PROSPECT

    def test_the_response_reports_whether_the_licence_is_current(self, client):
        pk = client.post(
            "/api/pharmacy-network/pharmacies/",
            registration_payload(slug="currency"), format="json",
        ).json()["id"]
        body = client.get(f"/api/pharmacy-network/pharmacies/{pk}/").json()
        assert body["profile"]["licence_is_current"] is True
        assert body["profile"]["days_until_licence_expiry"] == 200


class TestTheOldSurfaceIsClosed:
    """/api/tenancy/tenants/ is scoping infrastructure, not administration."""

    def test_a_tenant_cannot_be_created_there(self, client):
        response = client.post(
            "/api/tenancy/tenants/",
            {"name": "Backdoor", "slug": "backdoor"}, format="json",
        )
        assert response.status_code in (403, 405), (
            "A pharmacy can still be created outside the lifecycle, which means "
            "it can be made live with no licence and no branch."
        )

    def test_a_tenant_cannot_be_suspended_there(self, db, client):
        tenant = PharmacyOnboardingService.register_prospect(
            name="Old Route", slug="old-route", legal_name="Old Route Ltd"
        )
        response = client.post(
            f"/api/tenancy/tenants/{tenant.pk}/suspend/",
            {"reason": "Bypass."}, format="json",
        )
        assert response.status_code in (403, 404, 405)

    def test_reading_tenants_still_works(self, client):
        # The read side is used for scope pickers and must keep working.
        assert client.get("/api/tenancy/tenants/").status_code == 200
