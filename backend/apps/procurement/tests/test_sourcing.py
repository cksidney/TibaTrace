"""Competitive sourcing: request, quotation, award.

The tables and two half-methods existed; the cycle did not. Nothing could submit
a quotation, and `award_quotation` checked nothing at all -- not that the
quotation belonged to the RFQ it was awarding, not that the tender was still
open, not that the supplier was still approved.

That is the shape of a procurement fraud rather than a bug: the paperwork reads
as a competitive process either way.
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
from apps.procurement.models import (
    QuotationAward,
    RequestForQuotation,
    Supplier,
    SupplierQuotation,
)
from apps.procurement.services import SourcingService
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    from apps.core.tenant_context import set_current_tenant_id

    tenant = Tenant.objects.create(name="Sourcing Tenant", slug="sourcing-tenant")
    set_current_tenant_id(str(tenant.pk))
    buyer = User.objects.create_user(
        username="sourcing-buyer", password="password123", tenant=tenant
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-S", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-S", canonical_name="Paracetamol 500mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-S", brand_name="Panadol", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-S", display_name="Panadol 500mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    other_sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-S2", display_name="Panadol 1g",
        manufactured_product=manufactured, package_definition=pack,
    )
    return {"tenant": tenant, "buyer": buyer, "sku": sku, "other_sku": other_sku}


def a_supplier(world, code, status=Supplier.Status.APPROVED):
    return Supplier.all_objects.create(
        tenant=world["tenant"], supplier_code=code,
        legal_name=f"{code} Ltd", status=status,
    )


def an_rfq(world, days_open=7):
    return SourcingService.create_rfq(
        tenant=world["tenant"], title="Analgesics Q3",
        lines_data=[{"sku": world["sku"], "requested_quantity": 500}],
        closing_date=timezone.localdate() + datetime.timedelta(days=days_open),
    )


def a_quote(world, rfq, supplier, unit_cost, reference=None):
    return SourcingService.submit_quotation(
        rfq=rfq, supplier=supplier,
        quotation_reference=reference or f"Q-{supplier.supplier_code}",
        lines_data=[{
            "sku": world["sku"], "quoted_quantity": 500,
            "quoted_unit_cost": Decimal(unit_cost),
        }],
        valid_until=rfq.closing_date + datetime.timedelta(days=30),
    )


# ── the request ──────────────────────────────────────────────────────────────


class TestRaisingARequest:
    def test_an_rfq_is_numbered_and_opened(self, world):
        rfq = an_rfq(world)
        assert rfq.status == SourcingService.OPEN
        assert rfq.rfq_number.startswith("RFQ-")

    def test_numbers_do_not_repeat(self, world):
        """The original derived the number from a row count.

        Remove one RFQ and the next reuses a number that already exists in the
        audit trail.
        """
        first = an_rfq(world)
        second = an_rfq(world)
        assert first.rfq_number != second.rfq_number

        RequestForQuotation.all_objects.filter(pk=first.pk).delete()
        third = an_rfq(world)
        assert third.rfq_number != second.rfq_number

    def test_a_closing_date_in_the_past_is_refused(self, world):
        # A tender that closed before it opened cannot receive a quotation, so
        # every award against it is out of time by construction.
        with pytest.raises(ValidationError, match="cannot be in the past"):
            an_rfq(world, days_open=-1)

    def test_an_rfq_with_no_lines_is_refused(self, world):
        with pytest.raises(ValidationError, match="at least one line"):
            SourcingService.create_rfq(
                tenant=world["tenant"], title="Empty", lines_data=[],
                closing_date=timezone.localdate() + datetime.timedelta(days=7),
            )


# ── quotations ───────────────────────────────────────────────────────────────


class TestSubmittingAQuotation:
    def test_a_quotation_totals_its_own_lines(self, world):
        """The total is summed, not accepted from the caller.

        It is the number an award gets compared on, and a total that disagrees
        with its lines is the one nobody notices is wrong.
        """
        quote = a_quote(world, an_rfq(world), a_supplier(world, "SUP-A"), "12.00")
        assert quote.total_quoted_cost == Decimal("6000.00")

    def test_a_late_quotation_is_refused(self, world):
        rfq = an_rfq(world, days_open=1)
        rfq.closing_date = timezone.localdate() - datetime.timedelta(days=1)
        rfq.save(update_fields=["closing_date"])
        with pytest.raises(ValidationError, match="closed on"):
            a_quote(world, rfq, a_supplier(world, "SUP-LATE"), "10.00")

    def test_a_quotation_must_say_how_long_the_price_holds(self, world):
        # A price with no expiry is one the supplier can disown later and one a
        # buyer can hold them to forever.
        rfq = an_rfq(world)
        with pytest.raises(ValidationError, match="how long the price holds"):
            SourcingService.submit_quotation(
                rfq=rfq, supplier=a_supplier(world, "SUP-NOEXP"),
                quotation_reference="Q-NOEXP",
                lines_data=[{
                    "sku": world["sku"], "quoted_quantity": 10,
                    "quoted_unit_cost": Decimal("5.00"),
                }],
                valid_until=None,
            )

    def test_a_price_expiring_before_the_tender_closes_is_refused(self, world):
        rfq = an_rfq(world, days_open=30)
        with pytest.raises(ValidationError, match="at least until the tender closes"):
            SourcingService.submit_quotation(
                rfq=rfq, supplier=a_supplier(world, "SUP-SHORT"),
                quotation_reference="Q-SHORT",
                lines_data=[{
                    "sku": world["sku"], "quoted_quantity": 10,
                    "quoted_unit_cost": Decimal("5.00"),
                }],
                valid_until=timezone.localdate() + datetime.timedelta(days=2),
            )

    def test_a_suspended_supplier_cannot_quote(self, world):
        suspended = a_supplier(world, "SUP-SUSP", Supplier.Status.SUSPENDED)
        with pytest.raises(ValidationError, match="cannot quote"):
            a_quote(world, an_rfq(world), suspended, "10.00")

    def test_a_supplier_cannot_quote_twice_on_one_tender(self, world):
        # Two competing quotations from one supplier make "the lowest quote"
        # ambiguous.
        rfq = an_rfq(world)
        supplier = a_supplier(world, "SUP-TWICE")
        a_quote(world, rfq, supplier, "10.00")
        with pytest.raises(ValidationError, match="already quoted"):
            a_quote(world, rfq, supplier, "9.00", reference="Q-SECOND")

    def test_a_quotation_cannot_price_something_that_was_not_asked_for(self, world):
        rfq = an_rfq(world)
        with pytest.raises(ValidationError, match="only price products"):
            SourcingService.submit_quotation(
                rfq=rfq, supplier=a_supplier(world, "SUP-EXTRA"),
                quotation_reference="Q-EXTRA",
                lines_data=[{
                    "sku": world["other_sku"], "quoted_quantity": 10,
                    "quoted_unit_cost": Decimal("5.00"),
                }],
                valid_until=rfq.closing_date + datetime.timedelta(days=30),
            )


# ── the award ────────────────────────────────────────────────────────────────


class TestAwarding:
    def test_the_lowest_quotation_can_be_awarded_without_explanation(self, world):
        rfq = an_rfq(world)
        cheap = a_quote(world, rfq, a_supplier(world, "SUP-LOW"), "10.00")
        a_quote(world, rfq, a_supplier(world, "SUP-HIGH"), "12.00")

        award = SourcingService.award_quotation(
            rfq=rfq, winning_quotation=cheap, awarded_by=world["buyer"]
        )
        assert isinstance(award, QuotationAward)
        rfq.refresh_from_db()
        assert rfq.status == SourcingService.AWARDED

    def test_a_quotation_from_another_tender_cannot_win(self, world):
        """The hole this service was written to close.

        The previous implementation checked nothing, so a tender could be
        awarded to a quote submitted against an entirely different one -- and
        the paperwork still read as a competitive process.
        """
        rfq = an_rfq(world)
        a_quote(world, rfq, a_supplier(world, "SUP-OWN"), "10.00")

        other_rfq = an_rfq(world)
        outsider = a_quote(world, other_rfq, a_supplier(world, "SUP-OTHER"), "1.00")

        with pytest.raises(ValidationError, match="different request for quotation"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=outsider, awarded_by=world["buyer"]
            )

    def test_awarding_above_the_lowest_quote_requires_a_reason(self, world):
        """Legitimate -- quality, lead time, capacity -- but it has to be said.

        An unexplained award above the lowest quote is what an audit looks for.
        """
        rfq = an_rfq(world)
        a_quote(world, rfq, a_supplier(world, "SUP-CHEAP"), "10.00")
        dearer = a_quote(world, rfq, a_supplier(world, "SUP-DEAR"), "14.00")

        with pytest.raises(ValidationError, match="requires a stated reason"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=dearer, awarded_by=world["buyer"]
            )

        award = SourcingService.award_quotation(
            rfq=rfq, winning_quotation=dearer, awarded_by=world["buyer"],
            justification="Only supplier able to deliver within 48 hours.",
        )
        assert award.winning_quotation == dearer

    def test_the_reason_and_the_lowest_price_are_both_recorded(self, world):
        from apps.workflows.models import DomainEvent

        rfq = an_rfq(world)
        a_quote(world, rfq, a_supplier(world, "SUP-C2"), "10.00")
        dearer = a_quote(world, rfq, a_supplier(world, "SUP-D2"), "15.00")
        SourcingService.award_quotation(
            rfq=rfq, winning_quotation=dearer, awarded_by=world["buyer"],
            justification="Cold chain capability.",
        )
        event = DomainEvent.all_objects.filter(event_type="QuotationAwarded").first()
        assert event.payload["justification"] == "Cold chain capability."
        # What was passed over matters as much as what was chosen.
        assert event.payload["lowest_quoted_cost"] == "5000.00"

    def test_a_tender_cannot_be_awarded_twice(self, world):
        rfq = an_rfq(world)
        first = a_quote(world, rfq, a_supplier(world, "SUP-1"), "10.00")
        SourcingService.award_quotation(
            rfq=rfq, winning_quotation=first, awarded_by=world["buyer"]
        )
        with pytest.raises(ValidationError, match="already been awarded"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=first, awarded_by=world["buyer"]
            )

    def test_a_supplier_suspended_after_quoting_cannot_be_awarded(self, world):
        # The award would commit to a supplier governance has since stopped.
        rfq = an_rfq(world)
        supplier = a_supplier(world, "SUP-FALLS")
        quote = a_quote(world, rfq, supplier, "10.00")
        supplier.status = Supplier.Status.SUSPENDED
        supplier.save(update_fields=["status"])

        with pytest.raises(ValidationError, match="cannot be awarded to"):
            SourcingService.award_quotation(
                rfq=rfq, winning_quotation=quote, awarded_by=world["buyer"]
            )

    def test_losing_quotations_are_marked_rejected(self, world):
        """Leaving them SUBMITTED makes a closed tender look like it is still
        running."""
        rfq = an_rfq(world)
        winner = a_quote(world, rfq, a_supplier(world, "SUP-W"), "10.00")
        loser = a_quote(world, rfq, a_supplier(world, "SUP-L"), "12.00")
        SourcingService.award_quotation(
            rfq=rfq, winning_quotation=winner, awarded_by=world["buyer"]
        )
        loser.refresh_from_db()
        assert loser.status == SourcingService.REJECTED
        assert SupplierQuotation.all_objects.get(pk=winner.pk).status == SourcingService.ACCEPTED
