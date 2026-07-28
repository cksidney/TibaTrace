"""The pharmacy lifecycle, and whether its states do anything.

Before this module a tenant had two states and neither had force. A probe
confirmed it: with the tenant set to SUSPENDED, its user still signed in (200)
and still read the API (200). The status was a label, while HQ offered a
"Suspend" button with a confirmation dialog -- reporting an action that did not
happen.

The first class here is the one that matters. The rest guard the transitions and
the compliance gate around them.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.pharmacy_network.models import PharmacyProfile, TenantLifecycleEvent
from apps.pharmacy_network.services import (
    PharmacyOnboardingService,
    TenantLifecycleService,
)
from apps.tenancy.models import Tenant

PASSWORD = "lifecycle-password-long"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin(db):
    return User.objects.create_user(
        username="lifecycle-admin", password=PASSWORD, is_platform_admin=True
    )


def register(slug="green-cross", **overrides):
    fields = {
        "name": "Green Cross Pharmacy",
        "slug": slug,
        "legal_name": "Green Cross Pharmaceuticals Ltd",
        "business_registration_number": "PVT-2019-114",
        "ppb_premises_licence_number": "PPB/PREM/2026/0091",
        "ppb_licence_expiry": timezone.localdate() + timedelta(days=180),
        "superintendent_name": "Achieng Otieno",
        "superintendent_ppb_number": "PPB/PH/2015/2210",
    }
    fields.update(overrides)
    return PharmacyOnboardingService.register_prospect(**fields)


def take_live(slug="green-cross", **overrides):
    """A pharmacy all the way to trading, for tests about what happens after."""
    tenant = register(slug, **overrides)
    PharmacyOnboardingService.begin_onboarding(
        tenant=tenant, organization_name="Green Cross Group",
        organization_code="GCG", branch_name="Kisumu Branch", branch_code="GC-KSM",
    )
    return PharmacyOnboardingService.activate(tenant=tenant)


# ── the point of the whole module ────────────────────────────────────────────


class TestSuspensionActuallyStopsAPharmacy:
    def test_a_user_of_an_active_pharmacy_can_read(self, db):
        """The control. Without this, the next test proves nothing."""
        tenant = take_live()
        User.objects.create_user(username="gc-user", password=PASSWORD, tenant=tenant)
        client = APIClient()
        assert client.post(
            "/api/identity/session/",
            {"username": "gc-user", "password": PASSWORD}, format="json",
        ).status_code == 200
        assert client.get("/api/hq/overview/").status_code == 200

    def test_a_suspended_pharmacy_is_refused(self, db, admin):
        tenant = take_live(slug="suspended-cross")
        User.objects.create_user(username="sc-user", password=PASSWORD, tenant=tenant)
        client = APIClient()
        client.post(
            "/api/identity/session/",
            {"username": "sc-user", "password": PASSWORD}, format="json",
        )
        assert client.get("/api/hq/overview/").status_code == 200

        TenantLifecycleService.suspend(
            tenant=tenant, actor=admin, reason="Licence lapsed."
        )

        response = client.get("/api/hq/overview/")
        assert response.status_code == 403, (
            "A suspended pharmacy is still being served. Suspension is decorative "
            "again, and the HQ button reports an action that did not happen."
        )
        # The state is named so an operator can tell "not live yet" from
        # "stopped": those need different phone calls.
        assert response.json()["tenant_status"] == "SUSPENDED"

    def test_a_pharmacy_still_onboarding_cannot_trade(self, db):
        tenant = register(slug="not-yet-live")
        PharmacyOnboardingService.begin_onboarding(
            tenant=tenant, organization_name="Not Yet Group", organization_code="NYG",
            branch_name="Main", branch_code="NY-MAIN",
        )
        User.objects.create_user(username="ny-user", password=PASSWORD, tenant=tenant)
        client = APIClient()
        client.post(
            "/api/identity/session/",
            {"username": "ny-user", "password": PASSWORD}, format="json",
        )
        response = client.get("/api/hq/overview/")
        assert response.status_code == 403
        assert response.json()["tenant_status"] == "ONBOARDING"

    def test_a_platform_admin_can_still_see_a_suspended_pharmacy(self, db, admin):
        """Otherwise nobody could reinstate one."""
        tenant = take_live(slug="admin-visible")
        TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="Audit.")
        client = APIClient()
        client.post(
            "/api/identity/session/",
            {"username": "lifecycle-admin", "password": PASSWORD}, format="json",
        )
        assert client.get("/api/hq/overview/").status_code == 200


# ── the compliance gate ──────────────────────────────────────────────────────


class TestActivationRequiresALicence:
    def test_a_pharmacy_without_a_licence_cannot_be_activated(self, db):
        tenant = register(
            slug="unlicensed", ppb_premises_licence_number="", ppb_licence_expiry=None
        )
        PharmacyOnboardingService.begin_onboarding(
            tenant=tenant, organization_name="Unlicensed Group", organization_code="UNL",
            branch_name="Main", branch_code="UNL-MAIN",
        )
        with pytest.raises(ValidationError, match="premises licence"):
            PharmacyOnboardingService.activate(tenant=tenant)
        tenant.refresh_from_db()
        assert tenant.status == Tenant.STATUS_ONBOARDING

    def test_an_expired_licence_does_not_count(self, db):
        tenant = register(
            slug="expired-licence",
            ppb_licence_expiry=timezone.localdate() - timedelta(days=1),
        )
        PharmacyOnboardingService.begin_onboarding(
            tenant=tenant, organization_name="Expired Group", organization_code="EXP",
            branch_name="Main", branch_code="EXP-MAIN",
        )
        with pytest.raises(ValidationError, match="premises licence"):
            PharmacyOnboardingService.activate(tenant=tenant)

    def test_a_pharmacy_without_a_superintendent_cannot_be_activated(self, db):
        # Every registered premises must have a named superintendent pharmacist.
        tenant = register(slug="no-super", superintendent_name="")
        PharmacyOnboardingService.begin_onboarding(
            tenant=tenant, organization_name="No Super Group", organization_code="NSU",
            branch_name="Main", branch_code="NSU-MAIN",
        )
        with pytest.raises(ValidationError, match="superintendent"):
            PharmacyOnboardingService.activate(tenant=tenant)

    def test_reinstating_re_checks_the_licence(self, db, admin):
        """A pharmacy is often suspended *because* its licence lapsed."""
        tenant = take_live(slug="lapse-then-reinstate")
        TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="Licence query.")
        profile = tenant.pharmacy_profile
        profile.ppb_licence_expiry = timezone.localdate() - timedelta(days=2)
        profile.save(update_fields=["ppb_licence_expiry"])

        with pytest.raises(ValidationError, match="current premises licence"):
            TenantLifecycleService.reinstate(tenant=tenant, actor=admin)
        tenant.refresh_from_db()
        assert tenant.status == Tenant.STATUS_SUSPENDED


# ── the state machine ────────────────────────────────────────────────────────


class TestTransitions:
    def test_a_new_pharmacy_starts_as_a_prospect_not_live(self, db):
        # Creation used to produce a row that was live immediately and yet could
        # not do anything: no organization, no branch, nobody able to sign in.
        tenant = register(slug="fresh")
        assert tenant.status == Tenant.STATUS_PROSPECT

    def test_a_prospect_cannot_skip_straight_to_active(self, db):
        tenant = register(slug="skipper")
        with pytest.raises(ValidationError, match="cannot move from PROSPECT to ACTIVE"):
            TenantLifecycleService.transition(tenant=tenant, to_state=Tenant.STATUS_ACTIVE)

    def test_a_terminated_pharmacy_cannot_be_reinstated(self, db, admin):
        tenant = take_live(slug="closing-down")
        TenantLifecycleService.terminate(
            tenant=tenant, actor=admin, reason="Business closed."
        )
        with pytest.raises(ValidationError, match="cannot be reinstated"):
            TenantLifecycleService.reinstate(tenant=tenant, actor=admin)

    def test_suspending_without_a_reason_is_refused(self, db, admin):
        # An unexplained suspension is indistinguishable from an accident.
        tenant = take_live(slug="no-reason")
        with pytest.raises(ValidationError, match="requires a reason"):
            TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="   ")


# ── the record ───────────────────────────────────────────────────────────────


class TestEveryTransitionIsRecorded:
    def test_the_actor_and_reason_survive(self, db, admin):
        """The reason used to go into a JSON blob and be overwritten by the next
        suspension; the actor was not captured at all."""
        tenant = take_live(slug="recorded")
        TenantLifecycleService.suspend(
            tenant=tenant, actor=admin, reason="Stock discrepancy under review."
        )
        event = TenantLifecycleEvent.all_objects.filter(tenant=tenant).first()
        assert event.to_state == Tenant.STATUS_SUSPENDED
        assert event.from_state == Tenant.STATUS_ACTIVE
        assert event.actor == admin
        assert event.reason == "Stock discrepancy under review."

    def test_two_suspensions_both_survive(self, db, admin):
        tenant = take_live(slug="twice")
        TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="First.")
        TenantLifecycleService.reinstate(tenant=tenant, actor=admin, reason="Resolved.")
        TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="Second.")
        reasons = list(
            TenantLifecycleEvent.all_objects.filter(
                tenant=tenant, to_state=Tenant.STATUS_SUSPENDED
            ).values_list("reason", flat=True)
        )
        assert sorted(reasons) == ["First.", "Second."]

    def test_a_transition_writes_an_audit_event(self, db, admin):
        from apps.audit.models import AuditEvent

        tenant = take_live(slug="audited")
        TenantLifecycleService.suspend(tenant=tenant, actor=admin, reason="Checked.")
        assert AuditEvent.all_objects.filter(
            action="TENANT_SUSPENDED", object_id=str(tenant.pk)
        ).exists()


# ── provisioning ─────────────────────────────────────────────────────────────


class TestOnboardingProvisions:
    def test_beginning_onboarding_creates_the_structure_a_pharmacy_needs(self, db):
        from apps.organizations.models import Location, Organization

        tenant = register(slug="provisioned")
        PharmacyOnboardingService.begin_onboarding(
            tenant=tenant, organization_name="Provisioned Group",
            organization_code="pvg", branch_name="Nakuru Branch", branch_code="pv-nku",
        )
        assert Organization.all_objects.filter(tenant=tenant, code="PVG").exists()
        assert Location.all_objects.filter(tenant=tenant, code="PV-NKU").exists()
        tenant.refresh_from_db()
        assert tenant.status == Tenant.STATUS_ONBOARDING

    def test_a_licence_number_without_an_expiry_is_refused(self, db):
        # One without the other cannot be checked for currency.
        with pytest.raises(ValidationError, match="number and an expiry"):
            register(slug="half-licence", ppb_licence_expiry=None)

    def test_the_profile_records_when_the_pharmacy_went_live(self, db):
        tenant = take_live(slug="timestamped")
        profile = PharmacyProfile.all_objects.get(tenant=tenant)
        assert profile.onboarding_started_at is not None
        assert profile.activated_at is not None
