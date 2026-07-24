from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.sales.models import CustomerPriceAgreement, PriceList, PriceListEntry
from apps.sales.services import CommercialPricingService, QuotationService


@pytest.mark.django_db
class TestCommercialPricingService:
    def test_resolve_price_base_price(self, tenant_a, active_customer, sku):
        result = CommercialPricingService.resolve_price(tenant=tenant_a, customer=active_customer, sku=sku, quantity=1)
        assert result["agreed_unit_price"] == Decimal("0.00")
        assert result["base_unit_price"] == Decimal("0.00")
        assert result["discount_amount"] == Decimal("0.00")

    def test_resolve_price_price_list(self, tenant_a, active_customer, sku):
        pl = PriceList.objects.create(
            tenant=tenant_a,
            code="PL-DEFAULT",
            name="Default PL",
            effective_from="2020-01-01",
            is_default=True,
            status=PriceList.Status.ACTIVE,
        )
        PriceListEntry.objects.create(
            tenant=tenant_a, price_list=pl, sku=sku, unit_price=Decimal("90.00"), effective_from="2020-01-01"
        )

        result = CommercialPricingService.resolve_price(tenant=tenant_a, customer=active_customer, sku=sku, quantity=1)
        assert result["agreed_unit_price"] == Decimal("90.00")
        assert result["base_unit_price"] == Decimal("90.00")
        assert result["price_list_ref"] == str(pl.pk)

    def test_resolve_price_customer_agreement(self, tenant_a, active_customer, sku):
        CustomerPriceAgreement.objects.create(
            tenant=tenant_a,
            customer=active_customer,
            sku=sku,
            is_active=True,
            effective_from="2000-01-01",
            effective_to="2099-12-31",
            agreed_price=Decimal("80.00"),
            discount_percentage=Decimal("10.00"),
        )
        result = CommercialPricingService.resolve_price(tenant=tenant_a, customer=active_customer, sku=sku, quantity=1)
        assert result["base_unit_price"] == Decimal("80.00")
        assert result["discount_percentage"] == Decimal("10.00")
        assert result["discount_amount"] == Decimal("8.00")
        assert result["agreed_unit_price"] == Decimal("72.00")


@pytest.mark.django_db
class TestQuotationService:
    @pytest.fixture
    def draft_quotation(self, tenant_a, active_customer, test_user, branch):
        return QuotationService.create_quotation(
            tenant=tenant_a, branch=branch, customer=active_customer, created_by=test_user
        )

    def test_create_quotation(self, draft_quotation):
        assert draft_quotation.status == "DRAFT"
        assert draft_quotation.quotation_number.startswith("QT-")

    def test_add_quotation_line(self, draft_quotation, sku):
        line = QuotationService.add_quotation_line(
            quotation=draft_quotation,
            sku=sku,
            requested_quantity=2,
            unit="EA",
            pricing_data={
                "base_unit_price": Decimal("100.00"),
                "agreed_unit_price": Decimal("100.00"),
                "discount_amount": Decimal("0.00"),
                "discount_percentage": Decimal("0.00"),
                "price_list_ref": "",
            },
        )
        assert line.agreed_unit_price == Decimal("100.00")
        assert line.line_total == Decimal("200.00")
        draft_quotation.refresh_from_db()
        assert draft_quotation.total == Decimal("200.00")

    def test_quotation_lifecycle(self, draft_quotation, test_user, sku):
        QuotationService.add_quotation_line(
            quotation=draft_quotation,
            sku=sku,
            requested_quantity=1,
            unit="EA",
            pricing_data={
                "base_unit_price": Decimal("100.00"),
                "agreed_unit_price": Decimal("100.00"),
                "discount_amount": Decimal("0.00"),
                "discount_percentage": Decimal("0.00"),
                "price_list_ref": "",
            },
        )
        quotation = QuotationService.submit_quotation(quotation=draft_quotation)
        assert quotation.status == "SUBMITTED"

        quotation = QuotationService.approve_quotation(quotation=quotation, approver=test_user)
        assert quotation.status == "APPROVED"

        quotation = QuotationService.send_quotation(quotation=quotation)
        assert quotation.status == "SENT"

        quotation = QuotationService.accept_quotation(quotation=quotation)
        assert quotation.status == "ACCEPTED"

    def test_reject_quotation(self, draft_quotation):
        quotation = QuotationService.reject_quotation(quotation=draft_quotation, reason="Too expensive")
        assert quotation.status == "REJECTED"

    def test_revise_quotation(self, draft_quotation, test_user):
        initial_revision = draft_quotation.revision
        revision_record = QuotationService.revise_quotation(
            quotation=draft_quotation,
            changed_fields={"terms": "old"},
            previous_values={"terms": "old"},
            new_values={"terms": "new"},
            reason="Update terms",
            actor=test_user,
        )
        draft_quotation.refresh_from_db()
        assert draft_quotation.revision == initial_revision + 1
        assert revision_record.revision_number == initial_revision + 1

    def test_convert_quotation(self, draft_quotation, test_user, sku):
        QuotationService.add_quotation_line(
            quotation=draft_quotation,
            sku=sku,
            requested_quantity=1,
            unit="EA",
            pricing_data={
                "base_unit_price": Decimal("100.00"),
                "agreed_unit_price": Decimal("100.00"),
                "discount_amount": Decimal("0.00"),
                "discount_percentage": Decimal("0.00"),
                "price_list_ref": "",
            },
        )

        QuotationService.submit_quotation(quotation=draft_quotation)
        QuotationService.approve_quotation(quotation=draft_quotation, approver=test_user)
        QuotationService.send_quotation(quotation=draft_quotation)
        QuotationService.accept_quotation(quotation=draft_quotation)

        QuotationService.convert_quotation(quotation=draft_quotation, actor=test_user)
        draft_quotation.refresh_from_db()
        assert draft_quotation.status == "CONVERTED"

    def test_double_conversion_prevention(self, draft_quotation, test_user, sku):
        QuotationService.add_quotation_line(
            quotation=draft_quotation,
            sku=sku,
            requested_quantity=1,
            unit="EA",
            pricing_data={
                "base_unit_price": Decimal("100.00"),
                "agreed_unit_price": Decimal("100.00"),
                "discount_amount": Decimal("0.00"),
                "discount_percentage": Decimal("0.00"),
                "price_list_ref": "",
            },
        )
        QuotationService.submit_quotation(quotation=draft_quotation)
        QuotationService.approve_quotation(quotation=draft_quotation, approver=test_user)
        QuotationService.send_quotation(quotation=draft_quotation)
        QuotationService.accept_quotation(quotation=draft_quotation)

        QuotationService.convert_quotation(quotation=draft_quotation, actor=test_user)

        with pytest.raises(ValidationError, match="Only ACCEPTED quotations can be converted"):
            QuotationService.convert_quotation(quotation=draft_quotation, actor=test_user)
