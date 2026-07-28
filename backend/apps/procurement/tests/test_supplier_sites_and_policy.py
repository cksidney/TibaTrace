"""Supplier sites, and the award rule as configurable policy.

Two loose ends. `SupplierSite` was a table with no service, no route and nothing
referencing it. And awarding above the lowest quotation was hard-coded to
"require a stated reason" -- a defensible default, but a policy choice this
service had no business making for every organisation.
"""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.procurement.models import ProcurementPolicy, Supplier, SupplierSite
from apps.procurement.services import SourcingService, SupplierSiteService
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    from apps.core.tenant_context import set_current_tenant_id

    tenant = Tenant.objects.create(name="Site Tenant", slug="site-policy-tenant")
    set_current_tenant_id(str(tenant.pk))
    buyer = User.objects.create_user(
        username="site-buyer", password="password123", tenant=tenant
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-SP", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-SP", canonical_name="Losartan 50mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-SP", brand_name="Cozaar", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-SP", display_name="Cozaar 50mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    supplier = Supplier.all_objects.create(
        tenant=tenant, supplier_code="SUP-SITE", legal_name="Multi Depot Ltd",
        status=Supplier.Status.APPROVED,
    )
    return {"tenant": tenant, "buyer": buyer, "sku": sku, "supplier": supplier}


# ── supplier sites ───────────────────────────────────────────────────────────


class TestSupplierSites:
    def test_the_first_site_is_primary_whatever_the_caller_asked(self, world):
        """A supplier with sites but no primary has no default origin.

        Every downstream question -- where did this come from, where does a
        return go -- then has no answer.
        """
        site = SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="nbo", site_name="Nairobi Depot", is_primary=False,
        )
        assert site.is_primary is True
        # Codes are normalised, so NBO and nbo cannot both exist.
        assert site.site_code == "NBO"

    def test_a_duplicate_code_within_one_supplier_is_refused(self, world):
        # Two sites sharing a code make a delivery note ambiguous about which
        # depot it came from.
        SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="NBO", site_name="Nairobi Depot",
        )
        with pytest.raises(ValidationError, match="already has a site NBO"):
            SupplierSiteService.register_site(
                tenant=world["tenant"], supplier=world["supplier"],
                site_code="nbo", site_name="Nairobi Depot 2",
            )

    def test_two_suppliers_may_use_the_same_site_code(self, world):
        other = Supplier.all_objects.create(
            tenant=world["tenant"], supplier_code="SUP-OTHER",
            legal_name="Other Ltd", status=Supplier.Status.APPROVED,
        )
        SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="NBO", site_name="Nairobi",
        )
        # Uniqueness is per supplier, not global: everybody has a Nairobi depot.
        assert SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=other,
            site_code="NBO", site_name="Nairobi",
        ).site_code == "NBO"

    def test_promoting_a_site_demotes_the_previous_primary(self, world):
        """Two primaries is the same as none."""
        first = SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="NBO", site_name="Nairobi",
        )
        second = SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="MSA", site_name="Mombasa",
        )
        assert second.is_primary is False

        SupplierSiteService.set_primary_site(site=second)
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.is_primary is True
        assert first.is_primary is False
        assert SupplierSite.all_objects.filter(
            supplier=world["supplier"], is_primary=True
        ).count() == 1

    def test_registering_a_primary_demotes_the_incumbent(self, world):
        first = SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="NBO", site_name="Nairobi",
        )
        SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="KSM", site_name="Kisumu", is_primary=True,
        )
        first.refresh_from_db()
        assert first.is_primary is False

    def test_the_primary_can_be_looked_up(self, world):
        assert SupplierSiteService.primary_site_for(
            tenant=world["tenant"], supplier=world["supplier"]
        ) is None
        SupplierSiteService.register_site(
            tenant=world["tenant"], supplier=world["supplier"],
            site_code="NBO", site_name="Nairobi",
        )
        found = SupplierSiteService.primary_site_for(
            tenant=world["tenant"], supplier=world["supplier"]
        )
        assert found.site_code == "NBO"

    def test_a_site_requires_a_code_and_a_name(self, world):
        with pytest.raises(ValidationError, match="site code is required"):
            SupplierSiteService.register_site(
                tenant=world["tenant"], supplier=world["supplier"],
                site_code="  ", site_name="Nameless",
            )


# ── the award policy ─────────────────────────────────────────────────────────


def a_tender_with_two_quotes(world, cheap="10.00", dear="12.00"):
    rfq = SourcingService.create_rfq(
        tenant=world["tenant"], title="Antihypertensives",
        lines_data=[{"sku": world["sku"], "requested_quantity": 100}],
        closing_date=timezone.localdate() + datetime.timedelta(days=7),
    )
    quotes = {}
    for label, price in (("cheap", cheap), ("dear", dear)):
        supplier = Supplier.all_objects.create(
            tenant=world["tenant"], supplier_code=f"SUP-{label.upper()}",
            legal_name=f"{label} Ltd", status=Supplier.Status.APPROVED,
        )
        quotes[label] = SourcingService.submit_quotation(
            rfq=rfq, supplier=supplier, quotation_reference=f"Q-{label}",
            valid_until=rfq.closing_date + datetime.timedelta(days=30),
            lines_data=[{
                "sku": world["sku"], "quoted_quantity": 100,
                "quoted_unit_cost": Decimal(price),
            }],
        )
    return rfq, quotes


def set_policy(world, mode, tolerance="0.00"):
    return ProcurementPolicy.all_objects.create(
        tenant=world["tenant"], award_above_lowest=mode,
        award_variance_tolerance_percent=Decimal(tolerance),
    )


class TestAwardPolicyIsConfigurable:
    def test_the_default_still_requires_a_reason(self, world):
        """Unconfigured tenants keep the behaviour they had.

        `for_tenant` returns an unsaved default rather than creating a row, so a
        policy nobody set does not start existing because somebody looked at a
        tender.
        """
        rfq, quotes = a_tender_with_two_quotes(world)
        assert not ProcurementPolicy.all_objects.filter(tenant=world["tenant"]).exists()
        with pytest.raises(ValidationError, match="requires a stated reason"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"]
            )

    def test_block_refuses_the_award_outright(self, world):
        set_policy(world, ProcurementPolicy.AwardAboveLowest.BLOCK)
        rfq, quotes = a_tender_with_two_quotes(world)
        # A reason does not help: the policy is that the lowest wins.
        with pytest.raises(ValidationError, match="requires awarding the lowest"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"],
                justification="Better lead time.",
            )

    def test_allow_permits_it_without_explanation(self, world):
        set_policy(world, ProcurementPolicy.AwardAboveLowest.ALLOW)
        rfq, quotes = a_tender_with_two_quotes(world)
        award = SourcingService.award_quotation(
            rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"]
        )
        assert award.winning_quotation == quotes["dear"]

    def test_a_variance_inside_the_tolerance_needs_no_reason(self, world):
        """Awarding 1% above the lowest quote is rounding; 40% is a decision.

        Treating both alike trains buyers to type "cheapest declined" into every
        award, which is how a control becomes a formality.
        """
        set_policy(
            world, ProcurementPolicy.AwardAboveLowest.REQUIRE_REASON, tolerance="5.00"
        )
        rfq, quotes = a_tender_with_two_quotes(world, cheap="10.00", dear="10.20")
        award = SourcingService.award_quotation(
            rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"]
        )
        assert award is not None

    def test_a_variance_beyond_the_tolerance_still_needs_a_reason(self, world):
        set_policy(
            world, ProcurementPolicy.AwardAboveLowest.REQUIRE_REASON, tolerance="5.00"
        )
        rfq, quotes = a_tender_with_two_quotes(world, cheap="10.00", dear="14.00")
        with pytest.raises(ValidationError, match="40.00% above"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"]
            )

    def test_the_variance_is_recorded_whatever_the_policy(self, world):
        """A later audit asks how far above the lowest quote an award went.

        The answer must not depend on what the policy happened to be that month.
        """
        from apps.workflows.models import DomainEvent

        set_policy(world, ProcurementPolicy.AwardAboveLowest.ALLOW)
        rfq, quotes = a_tender_with_two_quotes(world, cheap="10.00", dear="15.00")
        SourcingService.award_quotation(
            rfq=rfq, winning_quotation=quotes["dear"], awarded_by=world["buyer"]
        )
        event = DomainEvent.all_objects.filter(event_type="QuotationAwarded").first()
        assert event.payload["variance_percent"] == "50.00"
        assert event.payload["policy"] == "ALLOW"

    def test_awarding_the_lowest_is_never_questioned(self, world):
        set_policy(world, ProcurementPolicy.AwardAboveLowest.BLOCK)
        rfq, quotes = a_tender_with_two_quotes(world)
        award = SourcingService.award_quotation(
            rfq=rfq, winning_quotation=quotes["cheap"], awarded_by=world["buyer"]
        )
        assert award.winning_quotation == quotes["cheap"]
