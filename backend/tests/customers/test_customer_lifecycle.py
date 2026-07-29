from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.customers.models import Customer, CustomerCommercialProfile
from apps.customers.services import CustomerCreditPolicyService, CustomerGovernanceService
from apps.identity.models import User


@pytest.fixture
def test_user(tenant_a):
    return User.objects.create_user(
        username="test_customer_admin", email="test_admin@example.com", password="password123", tenant=tenant_a
    )


@pytest.fixture
def new_customer(tenant_a, test_user):
    return CustomerGovernanceService.create_customer(
        tenant=tenant_a,
        customer_number="CUST-001",
        legal_name="Acme Corp",
        customer_type="RETAIL",
        created_by=test_user,
    )


@pytest.mark.django_db
class TestCustomerLifecycle:
    def test_customer_creation(self, tenant_a, test_user):
        customer = CustomerGovernanceService.create_customer(
            tenant=tenant_a,
            customer_number="CUST-002",
            legal_name="Wayne Enterprises",
            customer_type="WHOLESALE",
            created_by=test_user,
        )
        assert customer.id is not None
        assert customer.status == Customer.Status.UNDER_REVIEW
        assert customer.tenant == tenant_a

        # Test creation emits event implicitly handled if exceptions aren't raised

    def test_begin_review_customer(self, tenant_a, test_user):
        customer = CustomerGovernanceService.create_customer(
            tenant=tenant_a,
            customer_number="CUST-PROSPECT",
            legal_name="Prospective Customer",
            customer_type="RETAIL",
            created_by=test_user,
            status=Customer.Status.PROSPECTIVE,
        )

        customer = CustomerGovernanceService.begin_review_customer(
            customer=customer,
            actor=test_user,
            reason="Documents received",
        )

        assert customer.status == Customer.Status.UNDER_REVIEW

    def test_approve_customer(self, new_customer, test_user):
        customer = CustomerGovernanceService.approve_customer(
            customer=new_customer, approver=test_user, reason="Verified docs"
        )
        assert customer.status == Customer.Status.APPROVED
        assert customer.approved_by == test_user

    def test_approve_customer_invalid_status(self, new_customer, test_user):
        new_customer.status = Customer.Status.APPROVED
        new_customer.save()

        with pytest.raises(ValidationError, match="Customer must be UNDER_REVIEW to be approved."):
            CustomerGovernanceService.approve_customer(customer=new_customer, approver=test_user)

    def test_activate_customer(self, new_customer, test_user):
        CustomerGovernanceService.approve_customer(customer=new_customer, approver=test_user)
        customer = CustomerGovernanceService.activate_customer(customer=new_customer)
        assert customer.status == Customer.Status.ACTIVE

    def test_activate_customer_invalid_status(self, new_customer):
        with pytest.raises(ValidationError, match="Customer must be APPROVED to be activated."):
            CustomerGovernanceService.activate_customer(customer=new_customer)

    def test_suspend_customer(self, new_customer, test_user):
        CustomerGovernanceService.approve_customer(customer=new_customer, approver=test_user)
        CustomerGovernanceService.activate_customer(customer=new_customer)

        customer = CustomerGovernanceService.suspend_customer(customer=new_customer, reason="Missing payments")
        assert customer.status == Customer.Status.SUSPENDED

    def test_suspend_customer_invalid_status(self, new_customer):
        with pytest.raises(ValidationError, match="Customer must be ACTIVE to be suspended."):
            CustomerGovernanceService.suspend_customer(customer=new_customer, reason="Test")

    def test_block_customer(self, new_customer, test_user):
        customer = CustomerGovernanceService.block_customer(customer=new_customer, reason="Fraud detected")
        assert customer.status == Customer.Status.BLOCKED

    def test_reactivate_customer(self, new_customer, test_user):
        CustomerGovernanceService.approve_customer(customer=new_customer, approver=test_user)
        CustomerGovernanceService.activate_customer(customer=new_customer)
        CustomerGovernanceService.suspend_customer(customer=new_customer, reason="Late payment")

        customer = CustomerGovernanceService.reactivate_customer(customer=new_customer, reason="Payment received")
        assert customer.status == Customer.Status.ACTIVE

    def test_reactivate_customer_invalid_status(self, new_customer):
        with pytest.raises(ValidationError, match="Customer must be SUSPENDED to be reactivated."):
            CustomerGovernanceService.reactivate_customer(customer=new_customer, reason="Test")


@pytest.mark.django_db
class TestCustomerCreditPolicyService:
    @pytest.fixture
    def active_customer(self, tenant_a, test_user):
        c = CustomerGovernanceService.create_customer(
            tenant=tenant_a,
            customer_number="CUST-003",
            legal_name="Stark Ind",
            customer_type="RETAIL",
            created_by=test_user,
        )
        CustomerGovernanceService.approve_customer(customer=c, approver=test_user)
        CustomerGovernanceService.activate_customer(customer=c)
        return c

    def test_evaluate_order_inactive_customer(self, new_customer):
        # UNDER_REVIEW is not ACTIVE
        result = CustomerCreditPolicyService.evaluate_order(customer=new_customer, order_total=Decimal("100.00"))
        assert not result["eligible"]
        assert "status is UNDER_REVIEW" in result["reason"]

    def test_evaluate_order_credit_blocked(self, active_customer):
        active_customer.credit_status = Customer.CreditStatus.BLOCKED
        active_customer.save()
        result = CustomerCreditPolicyService.evaluate_order(customer=active_customer, order_total=Decimal("100.00"))
        assert not result["eligible"]
        assert "credit status is BLOCKED" in result["reason"]

    def test_evaluate_order_credit_hold(self, active_customer):
        active_customer.credit_status = Customer.CreditStatus.CREDIT_HOLD
        active_customer.save()
        result = CustomerCreditPolicyService.evaluate_order(customer=active_customer, order_total=Decimal("100.00"))
        assert not result["eligible"]
        assert "credit status is CREDIT_HOLD" in result["reason"]

    def test_evaluate_order_exceeds_credit_limit(self, tenant_a, active_customer):
        CustomerCommercialProfile.objects.create(
            tenant=tenant_a, customer=active_customer, credit_limit=Decimal("500.00")
        )
        # Refresh from db isn't needed if we fetch correctly, but let's re-fetch
        active_customer = Customer.objects.get(id=active_customer.id)

        result = CustomerCreditPolicyService.evaluate_order(customer=active_customer, order_total=Decimal("600.00"))
        assert not result["eligible"]
        assert result["reason"] == "Order exceeds credit limit"

    def test_evaluate_order_within_credit_limit(self, tenant_a, active_customer):
        CustomerCommercialProfile.objects.create(
            tenant=tenant_a, customer=active_customer, credit_limit=Decimal("500.00")
        )
        active_customer = Customer.objects.get(id=active_customer.id)

        result = CustomerCreditPolicyService.evaluate_order(customer=active_customer, order_total=Decimal("400.00"))
        assert result["eligible"]
        assert result["reason"] == ""
