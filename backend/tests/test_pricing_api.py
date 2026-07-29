"""The pricing workbench API, governed lifecycle and resolution query.

Two properties matter most. A price book is the one table where an unguarded
write changes what every till charges, so collections are read-only and changes
go through a draft/review/publish lifecycle. A quote is not a sale, so asking
what something costs records nothing.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role, User, UserRole
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pricing.models import (
    AppliedPriceSnapshot,
    PriceAssignment,
    PriceBook,
    PriceBookEntry,
    PriceBookVersion,
)
from apps.pricing.versioning import (
    APPROVE_CAPABILITY,
    MANAGE_CAPABILITY,
    PUBLISH_CAPABILITY,
)
from apps.tenancy.models import Tenant

TODAY = date.today()


def cash(value: str) -> Decimal:
    return Decimal(value)


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


def grant(user, *capabilities):
    role = Role.all_objects.create(
        tenant=user.tenant,
        code=f"role-{user.username}-{Role.all_objects.count()}",
        name="Pricing authority",
        capabilities=list(capabilities),
    )
    UserRole.all_objects.create(tenant=user.tenant, user=user, role=role)


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Pricing API Tenant", slug="pricing-api")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-PA", name="Group")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="ELD-PA", name="Eldoret")
    dose = DoseForm.objects.create(code="CAP-PA", name="Capsule")
    clinical = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-PA", canonical_name="Amoxicillin", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-PA", brand_name="Amoxil", clinical_product=clinical
    )
    package = PackageDefinition.objects.create(code="PK-PA", description="21", unit_of_measure="cap")
    sku = CommercialSKU.objects.create(
        tenant=tenant, sku_code="SKU-PA", display_name="Amoxil",
        manufactured_product=manufactured, package_definition=package,
    )
    user = User.objects.create_user(username="pricing-clerk", password="pw", tenant=tenant)
    api = APIClient()
    api.force_authenticate(user=user)
    return {"tenant": tenant, "branch": branch, "sku": sku, "user": user, "client": api}


def publish(world, *, code="TENANT-RETAIL", price="600.00", scope=PriceBook.ScopeType.TENANT,
            branch=None, status="ACTIVE"):
    book = PriceBook.all_objects.create(
        tenant=world["tenant"], code=code, name=code, scope_type=scope
    )
    version = PriceBookVersion.all_objects.create(
        tenant=world["tenant"], price_book=book, version_number=1,
        status=status, effective_from=TODAY - timedelta(days=30),
    )
    PriceBookEntry.all_objects.create(
        tenant=world["tenant"], version=version, sku=world["sku"], unit_price=cash(price)
    )
    PriceAssignment.all_objects.create(
        tenant=world["tenant"], price_book=book, scope_type=scope, branch=branch
    )
    return book, version


# ─── nothing writes ──────────────────────────────────────────────────────────


class TestReadOnly:
    """A price book is the one table where an unguarded write changes what
    every till charges."""

    @pytest.mark.parametrize(
        "collection", ["books", "versions", "entries", "assignments", "applied", "overrides"]
    )
    def test_collections_refuse_creation(self, world, collection):
        response = world["client"].post(f"/api/pricing/{collection}/", {}, format="json")
        assert response.status_code in (403, 405)

    def test_an_applied_price_cannot_be_edited_through_the_api(self, world):
        # It records what a customer was charged.
        response = world["client"].patch(
            "/api/pricing/applied/some-id/", {"unit_price": "1.00"}, format="json"
        )
        assert response.status_code in (403, 404, 405)

    def test_an_override_cannot_be_approved_through_the_api(self, world):
        """Approval checks the floor, the capability and that the approver is
        not the requester. A PATCH would skip all three."""
        response = world["client"].patch(
            "/api/pricing/overrides/some-id/", {"status": "APPROVED"}, format="json"
        )
        assert response.status_code in (403, 404, 405)


class TestPriceDraftWorkflow:
    def test_a_price_change_creates_a_draft_not_a_live_price(self, world):
        grant(world["user"], MANAGE_CAPABILITY)
        response = world["client"].post(
            "/api/pricing/prices/set-price/",
            {
                "sku_code": world["sku"].sku_code,
                "unit_price": "625.00",
                "minimum_allowed_price": "500.00",
                "tax_inclusive": True,
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "DRAFT"
        version = PriceBookVersion.all_objects.get(pk=response.json()["version_id"])
        assert version.status == PriceBookVersion.Status.DRAFT
        assert version.created_by == world["user"]

    def test_an_existing_live_price_is_never_edited(self, world):
        grant(world["user"], MANAGE_CAPABILITY)
        book, live = publish(world, code="DEFAULT-RETAIL", price="600.00")
        original = PriceBookEntry.all_objects.get(version=live, sku=world["sku"])

        response = world["client"].post(
            "/api/pricing/prices/set-price/",
            {"sku_code": world["sku"].sku_code, "unit_price": "625.00"},
            format="json",
        )

        assert response.status_code == 200
        original.refresh_from_db()
        assert original.unit_price == cash("600.00")
        draft = PriceBookVersion.all_objects.get(pk=response.json()["version_id"])
        assert draft.price_book == book
        assert draft.version_number == 2
        assert PriceBookEntry.all_objects.get(
            version=draft,
            sku=world["sku"],
        ).unit_price == cash("625.00")

    def test_pricing_requires_an_existing_commercial_sku(self, world):
        grant(world["user"], MANAGE_CAPABILITY)
        response = world["client"].post(
            "/api/pricing/prices/set-price/",
            {"sku_code": "GOVERNMENT-MASTER-ONLY", "unit_price": "625.00"},
            format="json",
        )
        assert response.status_code == 400
        assert "commercial sku" in response.json()["detail"].lower()

    def test_a_tenant_id_in_the_body_cannot_redirect_the_write(self, world):
        grant(world["user"], MANAGE_CAPABILITY)
        other = Tenant.objects.create(name="Other Pricing Tenant", slug="other-pricing")
        response = world["client"].post(
            "/api/pricing/prices/set-price/",
            {
                "tenant_id": str(other.pk),
                "sku_code": world["sku"].sku_code,
                "unit_price": "625.00",
            },
            format="json",
        )
        assert response.status_code == 200
        assert PriceBook.all_objects.filter(
            tenant=world["tenant"],
            code="DEFAULT-RETAIL",
        ).exists()
        assert not PriceBook.all_objects.filter(tenant=other).exists()

    def test_price_workflow_requires_separate_approval_then_publish(self, world):
        grant(world["user"], MANAGE_CAPABILITY, APPROVE_CAPABILITY)
        created = world["client"].post(
            "/api/pricing/prices/set-price/",
            {"sku_code": world["sku"].sku_code, "unit_price": "625.00"},
            format="json",
        ).json()
        version_id = created["version_id"]

        submitted = world["client"].post(
            f"/api/pricing/versions/{version_id}/submit/",
            {},
            format="json",
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == PriceBookVersion.Status.UNDER_REVIEW
        assert world["client"].post(
            f"/api/pricing/versions/{version_id}/approve/",
            {},
            format="json",
        ).status_code == 403

        approver = User.objects.create_user(
            username="pricing-approver",
            password="pw",
            tenant=world["tenant"],
        )
        grant(approver, APPROVE_CAPABILITY, PUBLISH_CAPABILITY)
        approver_client = APIClient()
        approver_client.force_authenticate(user=approver)
        approved = approver_client.post(
            f"/api/pricing/versions/{version_id}/approve/",
            {},
            format="json",
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == PriceBookVersion.Status.APPROVED

        published = approver_client.post(
            f"/api/pricing/versions/{version_id}/publish/",
            {},
            format="json",
        )
        assert published.status_code == 200
        assert published.json()["status"] == PriceBookVersion.Status.ACTIVE

    def test_price_draft_requires_management_authority(self, world):
        response = world["client"].post(
            "/api/pricing/prices/set-price/",
            {"sku_code": world["sku"].sku_code, "unit_price": "625.00"},
            format="json",
        )
        assert response.status_code == 403


# ─── resolution answers, and records nothing ─────────────────────────────────


class TestResolution:
    def test_a_price_resolves(self, world):
        publish(world)
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}&sku={world['sku'].pk}"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["unit_price"] == "600.00"
        assert body["source"] == "TENANT_PRICE"

    def test_a_quote_records_nothing(self, world):
        """A quote is not a sale.

        An endpoint that snapshotted every lookup would fill the applied-price
        table with charges that never happened.
        """
        publish(world)
        before = AppliedPriceSnapshot.all_objects.count()
        world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}&sku={world['sku'].pk}"
        )
        assert AppliedPriceSnapshot.all_objects.count() == before

    def test_the_answer_explains_itself(self, world):
        publish(world)
        publish(world, code="ELD-RETAIL", price="650.00",
                scope=PriceBook.ScopeType.BRANCH, branch=world["branch"])
        body = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}&sku={world['sku'].pk}"
        ).json()
        assert body["unit_price"] == "650.00"
        assert "TENANT_PRICE" in body["explanation"]
        assert len(body["considered"]) == 2

    def test_no_price_is_a_conflict_not_a_null(self, world):
        """A client receiving a price field is entitled to treat it as a price.

        There is no value that safely means "we could not work this out".
        """
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}&sku={world['sku'].pk}"
        )
        assert response.status_code == 409
        assert response.json()["code"] == "NO_PRICE_FOUND"

    def test_ambiguous_configuration_is_a_conflict(self, world):
        publish(world, code="ELD-A", price="650.00",
                scope=PriceBook.ScopeType.BRANCH, branch=world["branch"])
        publish(world, code="ELD-B", price="700.00",
                scope=PriceBook.ScopeType.BRANCH, branch=world["branch"])
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}&sku={world['sku'].pk}"
        )
        assert response.status_code == 409
        assert response.json()["code"] == "AMBIGUOUS_PRICING"

    def test_a_missing_branch_is_refused(self, world):
        # Resolving from an item alone is how one branch's price reaches
        # another branch's receipt.
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?sku={world['sku'].pk}"
        )
        assert response.status_code == 400
        assert "branch" in response.json()["detail"].lower()

    def test_a_malformed_quantity_is_refused(self, world):
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}"
            f"&sku={world['sku'].pk}&quantity=lots"
        )
        assert response.status_code == 400

    def test_a_malformed_date_is_refused(self, world):
        response = world["client"].get(
            f"/api/pricing/prices/resolve/?branch={world['branch'].pk}"
            f"&sku={world['sku'].pk}&service_date=yesterday"
        )
        assert response.status_code == 400

    def test_resolution_is_a_get(self, world):
        # A POST would invite an implementation that records the quote.
        publish(world)
        assert world["client"].post(
            "/api/pricing/prices/resolve/", {}, format="json"
        ).status_code in (403, 405)


# ─── isolation ───────────────────────────────────────────────────────────────


class TestIsolation:
    def test_another_tenants_price_books_are_not_listed(self, world, db):
        other = Tenant.objects.create(name="Rival", slug="rival-pricing")
        PriceBook.all_objects.create(
            tenant=other, code="THEIRS", name="Theirs", scope_type=PriceBook.ScopeType.TENANT
        )
        publish(world, code="MINE")

        codes = {row["code"] for row in rows(world["client"].get("/api/pricing/books/"))}
        assert "MINE" in codes
        assert "THEIRS" not in codes

    def test_an_unauthenticated_caller_is_refused(self, db):
        assert APIClient().get("/api/pricing/books/").status_code in (401, 403)

    def test_a_caller_without_a_tenant_sees_nothing(self, db):
        # A price list is commercially sensitive.
        user = User.objects.create_user(
            username="pricing-no-tenant", password="pw", is_platform_admin=True
        )
        api = APIClient()
        api.force_authenticate(user=user)
        assert rows(api.get("/api/pricing/books/")) == []


# ─── cost stays out ──────────────────────────────────────────────────────────


class TestCostConfidentiality:
    def test_no_serializer_exposes_cost(self):
        """An API serving both HQ and a till cannot be trusted to remember
        which caller it is answering, so cost is simply absent."""
        from apps.pricing.api import serializers as pricing_serializers

        source = open(pricing_serializers.__file__).read()
        for leak in ("unit_cost", "landed_cost", "weighted_average_cost", "margin"):
            assert leak not in source


class TestWorkbenchViews:
    def test_a_book_reports_its_live_version(self, world):
        publish(world)
        row = rows(world["client"].get("/api/pricing/books/"))[0]
        assert row["live_version"] == 1

    def test_a_book_with_only_a_draft_reports_no_live_version(self, world):
        # Configured but inert, which is worth seeing on the list rather than
        # discovering when nothing prices.
        publish(world, code="DRAFT-ONLY", status="DRAFT")
        row = next(
            r for r in rows(world["client"].get("/api/pricing/books/"))
            if r["code"] == "DRAFT-ONLY"
        )
        assert row["live_version"] is None

    def test_pending_overrides_can_be_filtered(self, world):
        assert world["client"].get(
            "/api/pricing/overrides/?pending=true"
        ).status_code == 200

    def test_every_collection_responds(self, world):
        for collection in (
            "books", "versions", "entries", "assignments", "applied", "overrides", "locks",
        ):
            assert world["client"].get(
                f"/api/pricing/{collection}/"
            ).status_code == 200, collection
