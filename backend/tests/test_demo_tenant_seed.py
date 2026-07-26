"""The composed demo tenant.

Its job is to make the platform clickable end to end, so the tests check the two
things that would stop it doing that: running twice must not duplicate, and the
data must reach the APIs a client actually calls.

The scenarios are deliberately awkward -- a branch that inherits rather than
overrides, a till that closed short. A happy-path demo shows the parts that were
always going to work.
"""
from decimal import Decimal

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.organizations.models import Location, Organization
from apps.pos_shift.models import (
    BusinessDay,
    CashDeclaration,
    CashMovement,
    PosRegister,
    RegisterSession,
    ShiftReport,
)
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion
from apps.tenancy.models import Tenant

SEEDED = [
    Tenant, Organization, Location, PosRegister, BusinessDay, RegisterSession,
    CashDeclaration, CashMovement, ShiftReport,
    PriceBook, PriceBookVersion, PriceBookEntry, PriceAssignment,
]


def counts() -> dict[str, int]:
    # Tenant is not itself tenant-scoped, so it has no all_objects manager.
    return {
        model.__name__: (
            model.all_objects if hasattr(model, "all_objects") else model.objects
        ).count()
        for model in SEEDED
    }


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def seeded(db):
    call_command("seed_demo_tenant")
    return counts()


@pytest.fixture
def client(seeded):
    tenant = Tenant.objects.get(slug="tibatrace-demo")
    user = User.objects.get(username="demo-operator")
    assert user.tenant_id == tenant.pk
    api = APIClient()
    api.force_authenticate(user=user)
    return api


# ─── idempotence ─────────────────────────────────────────────────────────────


class TestIdempotence:
    def test_running_twice_creates_nothing_new(self, seeded):
        call_command("seed_demo_tenant")
        assert counts() == seeded

    def test_running_three_times_is_stable(self, seeded):
        call_command("seed_demo_tenant")
        call_command("seed_demo_tenant")
        assert counts() == seeded

    def test_the_seed_creates_something(self, seeded):
        # A seed that creates nothing passes every idempotence test.
        assert seeded["Location"] >= 2
        assert seeded["PriceBook"] >= 2
        assert seeded["ShiftReport"] >= 1

    def test_only_one_tenant_is_created(self, seeded):
        """Nine seeds already existed and none composed.

        Each built its own tenant, so running them all left several unrelated
        organisations rather than one pharmacy anybody could click through.
        """
        assert Tenant.objects.filter(slug="tibatrace-demo").count() == 1


# ─── the awkward states are present ──────────────────────────────────────────


class TestScenarios:
    def test_one_branch_inherits_and_one_overrides(self, client):
        """The inheritance is the demonstration.

        A seed where every branch overrides would hide the sparsity the design
        exists for.
        """
        from datetime import date

        from apps.pricing.catalogue import PriceCatalogue
        from apps.pricing.resolution import PricingContext

        tenant = Tenant.objects.get(slug="tibatrace-demo")
        sku = tenant.commercial_skus.first() if hasattr(tenant, "commercial_skus") else None
        from apps.medicines.models import CommercialSKU

        sku = sku or CommercialSKU.all_objects.get(tenant=tenant, sku_code="DEMO-SKU-AMOX")
        eldoret = Location.all_objects.get(tenant=tenant, code="DEMO-ELD")
        mombasa = Location.all_objects.get(tenant=tenant, code="DEMO-MSA")

        def price_at(branch):
            return PriceCatalogue.price(
                context=PricingContext(
                    tenant_id=str(tenant.pk), branch_id=str(branch.pk),
                    sku_id=str(sku.pk), service_date=date.today(),
                )
            )

        assert price_at(eldoret).unit_price == Decimal("650.00")
        assert price_at(eldoret).source == "BRANCH_PRICE"
        assert price_at(mombasa).unit_price == Decimal("600.00")
        assert price_at(mombasa).source == "TENANT_PRICE"

    def test_one_product_master_serves_both_prices(self, seeded):
        from apps.medicines.models import CommercialSKU

        tenant = Tenant.objects.get(slug="tibatrace-demo")
        assert CommercialSKU.all_objects.filter(tenant=tenant).count() == 1

    def test_the_demo_till_closed_short(self, client):
        """A demo that balances never shows the variance workflow, which is the
        part anybody operating a pharmacy needs to see."""
        body = rows(client.get("/api/pos/shift/reports/variances/"))
        assert len(body) == 1
        variance = body[0]["snapshot"]["variance"]
        assert variance["classification"] == "SHORT"
        assert variance["difference"] == "-50.00"

    def test_the_expected_cash_accounts_for_the_safe_drop(self, client):
        # 5000 opening less 2000 to the safe is 3000 expected, 2950 counted.
        body = rows(client.get("/api/pos/shift/reports/"))
        report = next(r for r in body if r["report_type"] == "Z")
        assert report["snapshot"]["cash"]["opening"] == "5000.00"
        assert report["snapshot"]["cash"]["cash_out"] == "2000.00"
        assert report["snapshot"]["cash"]["expected_closing"] == "3000.00"


# ─── the data reaches the APIs a client calls ────────────────────────────────


class TestReachableThroughTheApi:
    def test_the_pricing_api_serves_the_seeded_books(self, client):
        codes = {row["code"] for row in rows(client.get("/api/pricing/books/"))}
        assert {"DEMO-TENANT-RETAIL", "DEMO-ELD-RETAIL"} <= codes

    def test_the_resolution_endpoint_answers_for_the_demo_branch(self, client):
        from apps.medicines.models import CommercialSKU

        tenant = Tenant.objects.get(slug="tibatrace-demo")
        sku = CommercialSKU.all_objects.get(tenant=tenant, sku_code="DEMO-SKU-AMOX")
        eldoret = Location.all_objects.get(tenant=tenant, code="DEMO-ELD")

        response = client.get(
            f"/api/pricing/prices/resolve/?branch={eldoret.pk}&sku={sku.pk}"
        )
        assert response.status_code == 200
        assert response.json()["unit_price"] == "650.00"

    def test_the_shift_api_serves_the_closed_session(self, client):
        body = rows(client.get("/api/pos/shift/sessions/"))
        assert len(body) == 1
        assert body[0]["has_final_report"] is True

    def test_no_till_is_left_open(self, client):
        # The seed closes what it opens, so the open-sessions list is a
        # meaningful signal rather than permanently showing the demo till.
        assert rows(client.get("/api/pos/shift/sessions/open/")) == []


# ─── the seed invents nothing ────────────────────────────────────────────────


class TestSeedHonesty:
    def test_the_seed_fabricates_no_insurer_or_quality_decision(self):
        """Seeded data carrying an approval nobody granted teaches people that
        approvals appear on their own."""
        from apps.platform.management.commands import seed_demo_tenant as mod

        source = open(mod.__file__).read()
        for forbidden in (
            "ClaimAdjudication", "adjudication_state", "approved_amount",
            "QualityDecision", "release_batch",
        ):
            assert forbidden not in source

    def test_the_z_report_came_from_the_service(self):
        # Not written directly. The service is what enforces one Z per session
        # and the closure preconditions.
        from apps.platform.management.commands import seed_demo_tenant as mod

        source = open(mod.__file__).read()
        assert "ShiftReportService.finalise_z" in source
        assert "ShiftReport.all_objects.create" not in source
