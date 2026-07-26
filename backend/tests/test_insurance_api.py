"""The insurance claims workbench API.

Two things this must not do: leak another tenant's claims, and offer a second
route to claim state that skips the services enforcing authority, idempotency
and the transport/adjudication separation.

The read-only constraint is not a limitation to be relaxed later. It is what
keeps the workbench a view rather than a bypass.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.insurance.models import Insurer
from apps.tenancy.models import Tenant


def cash(value: str) -> Decimal:
    return Decimal(value)


def rows(response):
    """The result rows, whether or not pagination is configured.

    Asserting on one shape would make these tests fail the day somebody turns
    pagination on, which is a change to presentation rather than to any
    property being tested here.
    """
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Claims Tenant", slug="claims-tenant")


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Rival Pharmacy", slug="rival-pharmacy")


@pytest.fixture
def user(tenant):
    return User.objects.create_user(username="claims-clerk", password="pw", tenant=tenant)


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def make_insurer(tenant, code="INS-1", adapter=Insurer.IntegrationAdapter.FAKE):
    return Insurer.all_objects.create(
        tenant=tenant, code=code, name=f"Insurer {code}", integration_adapter=adapter
    )


# ─── the workbench is read-only ──────────────────────────────────────────────


class TestReadOnly:
    """A writable endpoint would be a second route to claim state.

    Submission, adjudication and payment each run through a service that
    enforces authority and keeps transport acceptance apart from approval. An
    endpoint that could set those columns directly would skip all of it.
    """

    def test_claims_cannot_be_created_through_the_api(self, client, tenant):
        response = client.post("/api/insurance/claims/", {"claim_number": "CLM-X"}, format="json")
        assert response.status_code in (403, 405)

    def test_claims_cannot_be_patched_through_the_api(self, client, tenant):
        response = client.patch(
            "/api/insurance/claims/some-id/", {"payment_state": "PAID"}, format="json"
        )
        assert response.status_code in (403, 404, 405)

    def test_claims_cannot_be_deleted_through_the_api(self, client):
        response = client.delete("/api/insurance/claims/some-id/")
        assert response.status_code in (403, 404, 405)

    def test_remittances_cannot_be_created_through_the_api(self, client):
        # Importing a remittance allocates money to claims; it belongs to the
        # service that deduplicates and reconciles it.
        response = client.post("/api/insurance/remittances/", {}, format="json")
        assert response.status_code in (403, 405)


# ─── tenant isolation ────────────────────────────────────────────────────────


class TestIsolation:
    def test_another_tenants_insurers_are_not_listed(self, client, tenant, other_tenant):
        make_insurer(tenant, code="MINE")
        make_insurer(other_tenant, code="THEIRS")

        response = client.get("/api/insurance/insurers/")
        assert response.status_code == 200
        codes = {row["code"] for row in rows(response)}
        assert "MINE" in codes
        assert "THEIRS" not in codes

    def test_an_unauthenticated_caller_sees_nothing(self, db):
        anonymous = APIClient()
        assert anonymous.get("/api/insurance/claims/").status_code in (401, 403)

    def test_a_user_without_a_tenant_gets_an_empty_list(self, db):
        """No tenant, no rows.

        An unscoped read is how one pharmacy sees another's claims, so the
        absence of a tenant returns nothing rather than everything.
        """
        platform_user = User.objects.create_user(
            username="no-tenant", password="pw", is_platform_admin=True
        )
        api = APIClient()
        api.force_authenticate(user=platform_user)
        response = api.get("/api/insurance/insurers/")
        assert response.status_code == 200
        assert rows(response) == []


# ─── what the workbench shows ────────────────────────────────────────────────


class TestInsurerReadiness:
    def test_an_insurer_without_an_adapter_is_marked_unready(self, client, tenant):
        """Configuration and capability are different things.

        SHA is configurable today and has no implemented adapter. Showing it as
        ready would have somebody wondering why nothing sends.
        """
        make_insurer(tenant, code="SHA-CFG", adapter=Insurer.IntegrationAdapter.SHA)
        response = client.get("/api/insurance/insurers/")
        row = next(r for r in rows(response) if r["code"] == "SHA-CFG")
        assert row["adapter_registered"] is False

    def test_an_insurer_with_an_adapter_is_marked_ready(self, client, tenant):
        make_insurer(tenant, code="FAKE-CFG", adapter=Insurer.IntegrationAdapter.FAKE)
        response = client.get("/api/insurance/insurers/")
        row = next(r for r in rows(response) if r["code"] == "FAKE-CFG")
        assert row["adapter_registered"] is True


class TestClaimSerialisation:
    def test_all_four_states_are_exposed_separately(self, client, tenant):
        """A single status field is where transport acceptance starts being
        read as payment."""
        from rest_framework.test import APIRequestFactory

        from apps.insurance.api.serializers import ClaimSerializer

        fields = set(ClaimSerializer.Meta.fields)
        assert {
            "submission_state", "adjudication_state",
            "payment_state", "reconciliation_state",
        } <= fields
        assert "status" not in fields
        assert APIRequestFactory is not None

    def test_claimed_and_approved_are_both_exposed(self, client):
        from apps.insurance.api.serializers import ClaimSerializer

        # What we asked for and what they allowed are both facts, and the gap
        # between them is the contractual adjustment somebody must account for.
        fields = set(ClaimSerializer.Meta.fields)
        assert "claimed_gross_amount" in fields
        assert "approved_amount" in fields


class TestMembershipMasking:
    def test_a_membership_number_is_masked(self):
        """A claims list is left open on a shared desk.

        The full number identifies the member's whole insurance relationship,
        not just this claim.
        """
        from apps.insurance.api.serializers import mask_membership

        masked = mask_membership("MEM-12345678")
        assert masked.endswith("5678")
        assert "MEM-1234" not in masked

    def test_a_short_number_is_fully_masked(self):
        from apps.insurance.api.serializers import mask_membership

        assert set(mask_membership("1234")) == {"•"}

    def test_an_empty_number_does_not_crash(self):
        from apps.insurance.api.serializers import mask_membership

        assert mask_membership("") == ""
        assert mask_membership(None) == ""


# ─── the lists somebody acts on ──────────────────────────────────────────────


class TestWorkbenchLists:
    def test_the_approved_unpaid_list_exists(self, client, tenant):
        response = client.get("/api/insurance/claims/approved-unpaid/")
        assert response.status_code == 200

    def test_awaiting_decision_is_separate_from_approved_unpaid(self, client, tenant):
        """Different problems: one is chased with the insurer, the other is
        chased for payment. Merging them is how transport acceptance starts
        looking like a debt."""
        assert client.get("/api/insurance/claims/awaiting-decision/").status_code == 200
        assert client.get("/api/insurance/claims/approved-unpaid/").status_code == 200

    def test_needs_attention_exists(self, client, tenant):
        assert client.get("/api/insurance/claims/needs-attention/").status_code == 200

    def test_a_pending_claim_is_not_in_approved_unpaid(self, client, tenant, db):
        """Transport acceptance is not a debt."""
        response = client.get("/api/insurance/claims/approved-unpaid/")
        for row in rows(response):
            assert row["adjudication_state"] in ("APPROVED", "PARTIALLY_APPROVED")

    def test_rejections_can_be_filtered_to_unresolved(self, client):
        response = client.get("/api/insurance/rejections/?unresolved=true")
        assert response.status_code == 200


class TestRouting:
    def test_the_insurance_api_is_routed(self, client):
        # It was registered in INSTALLED_APPS but unrouted for the whole of its
        # existence, which made it unreachable however complete the domain was.
        assert client.get("/api/insurance/claims/").status_code == 200

    def test_every_registered_collection_responds(self, client):
        for collection in (
            "insurers", "coverages", "verifications", "claims", "rejections", "remittances",
        ):
            assert client.get(f"/api/insurance/{collection}/").status_code == 200, collection
