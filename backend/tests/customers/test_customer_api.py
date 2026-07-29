import pytest
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.identity.models import User


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def customer_payload(number="CUST-001"):
    return {
        "customer_number": number,
        "legal_name": "Nairobi Health Chemists Ltd",
        "customer_type": "PHARMACY",
        "risk_classification": "LOW",
        "controlled_medicine_eligible": True,
    }


@pytest.mark.django_db
class TestCustomerCreateAPI:
    def test_creates_an_under_review_customer_for_the_authenticated_tenant(self, tenant_a):
        user = User.objects.create_user(username="customer-admin", password="pw", tenant=tenant_a)
        response = authenticated_client(user).post(
            "/api/customers/customers/",
            customer_payload(" cust-001 "),
            format="json",
        )

        assert response.status_code == 201
        customer = Customer.all_objects.get(customer_number="CUST-001")
        assert customer.tenant == tenant_a
        assert customer.created_by == user
        assert customer.status == Customer.Status.UNDER_REVIEW

    def test_platform_admin_can_create_inside_the_selected_tenant(self, tenant_b):
        user = User.objects.create_user(
            username="platform-customer-admin",
            password="pw",
            is_platform_admin=True,
        )
        response = authenticated_client(user).post(
            "/api/customers/customers/",
            customer_payload(),
            format="json",
            HTTP_X_TENANT_ID=str(tenant_b.pk),
        )

        assert response.status_code == 201
        assert Customer.all_objects.get(customer_number="CUST-001").tenant == tenant_b

    def test_platform_admin_must_select_a_tenant(self, db):
        user = User.objects.create_user(
            username="unscoped-customer-admin",
            password="pw",
            is_platform_admin=True,
        )
        response = authenticated_client(user).post(
            "/api/customers/customers/",
            customer_payload(),
            format="json",
        )

        assert response.status_code == 400
        assert "tenant" in response.json()

    def test_tenant_user_cannot_select_another_tenant(self, tenant_a, tenant_b):
        user = User.objects.create_user(username="tenant-customer-admin", password="pw", tenant=tenant_a)
        response = authenticated_client(user).post(
            "/api/customers/customers/",
            customer_payload(),
            format="json",
            HTTP_X_TENANT_ID=str(tenant_b.pk),
        )

        assert response.status_code == 403
        assert not Customer.all_objects.filter(customer_number="CUST-001").exists()

    def test_duplicate_customer_number_is_a_validation_error(self, tenant_a):
        user = User.objects.create_user(username="duplicate-customer-admin", password="pw", tenant=tenant_a)
        client = authenticated_client(user)
        assert client.post(
            "/api/customers/customers/",
            customer_payload(),
            format="json",
        ).status_code == 201

        duplicate = client.post(
            "/api/customers/customers/",
            customer_payload(),
            format="json",
        )

        assert duplicate.status_code == 400
        assert "customer_number" in duplicate.json()

    def test_customer_governance_lifecycle_uses_explicit_transitions(self, tenant_a):
        user = User.objects.create_user(username="lifecycle-admin", password="pw", tenant=tenant_a)
        customer = Customer.all_objects.create(
            tenant=tenant_a,
            customer_number="CUST-LIFECYCLE",
            legal_name="Lifecycle Customer",
            customer_type=Customer.CustomerType.RETAIL,
            status=Customer.Status.PROSPECTIVE,
        )
        client = authenticated_client(user)
        transitions = (
            ("begin-review", Customer.Status.UNDER_REVIEW),
            ("approve", Customer.Status.APPROVED),
            ("activate", Customer.Status.ACTIVE),
            ("suspend", Customer.Status.SUSPENDED),
            ("reactivate", Customer.Status.ACTIVE),
        )

        for action, expected_status in transitions:
            response = client.post(
                f"/api/customers/customers/{customer.pk}/{action}/",
                {"reason": f"Business reason for {action}"},
                format="json",
            )
            assert response.status_code == 200, response.json()
            customer.refresh_from_db()
            assert customer.status == expected_status

    def test_governance_transition_requires_a_reason(self, tenant_a):
        user = User.objects.create_user(username="reason-admin", password="pw", tenant=tenant_a)
        customer = Customer.all_objects.create(
            tenant=tenant_a,
            customer_number="CUST-REASON",
            legal_name="Reason Customer",
            customer_type=Customer.CustomerType.RETAIL,
            status=Customer.Status.UNDER_REVIEW,
        )

        response = authenticated_client(user).post(
            f"/api/customers/customers/{customer.pk}/approve/",
            {"reason": "  "},
            format="json",
        )

        assert response.status_code == 400
        assert "reason" in response.json()
