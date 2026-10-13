import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.identity.models import Role, User, UserRole
from apps.pricing.models import PriceAssignment, PriceBook
from apps.sales.models import PriceList
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def client_for(user, tenant=None, *, header=True):
    client = APIClient()
    credentials = {"HTTP_AUTHORIZATION": "Bearer " + str(AccessToken.for_user(user))}
    if header:
        credentials["HTTP_X_TENANT_ID"] = str((tenant or user.tenant).pk)
    client.credentials(**credentials)
    return client


@pytest.fixture
def actors(db):
    a = Tenant.objects.create(name="Security A", slug="security-a")
    b = Tenant.objects.create(name="Security B", slug="security-b")
    user = User.objects.create_user(username="security-user", tenant=a, password="Temporary-Pass-56382!")
    return a, b, user


@pytest.mark.parametrize("path", ["/api/hq/workspace/", "/api/inventory/locations/", "/api/medicines/initial-setup/", "/api/sales/price-lists/"])
def test_bearer_cannot_select_other_tenant(actors, path):
    a, b, user = actors
    assert client_for(user, b).get(path).status_code == 403


def test_session_cannot_select_other_tenant(actors):
    a, b, user = actors
    client = APIClient()
    client.force_login(user)
    assert client.get("/api/hq/workspace/", HTTP_X_TENANT_ID=str(b.pk)).status_code == 403


def test_suspended_bearer_is_blocked_without_header(actors):
    a, b, user = actors
    a.status = Tenant.STATUS_SUSPENDED
    a.save(update_fields=["status"])
    assert client_for(user, header=False).get("/api/sales/price-lists/").status_code == 403


def test_platform_explicit_scope_and_invalid_scope(actors):
    a, b, user = actors
    admin = User.objects.create_user(username="security-admin", is_platform_admin=True)
    assert client_for(admin, b).get("/api/hq/workspace/").status_code == 200
    client = client_for(user)
    client.credentials(HTTP_AUTHORIZATION="Bearer " + str(AccessToken.for_user(user)), HTTP_X_TENANT_ID="not-a-uuid")
    assert client.get("/api/hq/workspace/").status_code == 403


def test_password_gate_and_change_revokes_old_bearer(actors):
    a, b, user = actors
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])
    client = client_for(user)
    assert client.get("/api/hq/workspace/").json()["code"] == "password_change_required"
    assert client.get("/api/identity/session/").json()["user"]["must_change_password"] is True
    result = client.post("/api/identity/password/change/", {
        "current_password": "Temporary-Pass-56382!", "new_password": "New-Secure-Pass-773921!",
    }, format="json")
    assert result.status_code == 200, result.data
    user.refresh_from_db()
    assert not user.must_change_password
    assert client.get("/api/hq/workspace/").status_code == 401
    assert client_for(user).get("/api/hq/workspace/").status_code == 200


def test_price_get_is_read_only_and_unauthorised_b2b_write_is_denied(actors):
    a, b, user = actors
    role = Role.all_objects.create(tenant=a, code="PRICING-READ",
                                  name="Pricing reader", capabilities=["pricing.read"])
    UserRole.all_objects.create(tenant=a, user=user, role=role)
    client = client_for(user)
    before = (PriceBook.all_objects.count(), PriceAssignment.all_objects.count())
    assert client.get("/api/pricing/books/").status_code == 200
    assert before == (PriceBook.all_objects.count(), PriceAssignment.all_objects.count())
    record = PriceList.all_objects.create(tenant=a, code="P", name="Prices", effective_from="2026-10-11")
    assert client.patch(f"/api/sales/price-lists/{record.pk}/", {"name": "Attack"}, format="json").status_code == 403


def test_b2b_authorised_creation_attaches_tenant(actors):
    a, b, user = actors
    role = Role.all_objects.create(tenant=a, code="PRICING", name="Pricing", capabilities=["pricing.manage"])
    UserRole.all_objects.create(tenant=a, user=user, role=role)
    result = client_for(user).post("/api/sales/price-lists/", {
        "code": "PR", "name": "Prices", "effective_from": "2026-10-11", "change_reason": "Initial prices",
    }, format="json")
    assert result.status_code == 201, result.data
    assert PriceList.all_objects.get(pk=result.data["id"]).tenant_id == a.pk


def test_fake_provider_is_rejected_for_real_production_tenant(actors):
    from django.core.exceptions import ValidationError

    from apps.prescription.payment_providers import FakeProviderAdapter

    with override_settings(DEBUG=False, TESTING=False), pytest.raises(ValidationError):
        FakeProviderAdapter().validate_configuration(tenant=actors[0])


def test_fake_insurer_is_rejected_for_real_production_tenant(actors):
    from django.core.exceptions import ValidationError

    from apps.insurance.adapters.base import require_real_adapter_for_production
    from apps.insurance.adapters.fake import FakeInsurerAdapter

    with override_settings(DEBUG=False, TESTING=False), pytest.raises(ValidationError):
        require_real_adapter_for_production(tenant_id=actors[0].pk, adapter=FakeInsurerAdapter())


@pytest.mark.parametrize("path", [
    "/api/nif/platform/providers/", "/api/nif/platform/activations/",
    "/api/nif/platform/evidence/", "/api/nif/platform/reports/",
])
def test_national_platform_routes_require_explicit_platform_authority(actors, path):
    assert client_for(actors[2]).get(path).status_code == 403


def test_disabled_templates_are_idempotent_and_preserve_live_configuration():
    from django.core.management import call_command

    from apps.integrations.models import ProviderConfiguration, ProviderCredentialReference

    call_command("provision_integration_templates")
    assert ProviderConfiguration.objects.count() == 16
    assert not any(p.is_operational for p in ProviderConfiguration.objects.all())
    assert not ProviderCredentialReference.objects.filter(is_configured=True).exists()
    record = ProviderConfiguration.objects.get(provider_type="DHA_HWR", environment="SANDBOX")
    record.notes = "Preserve approved operator notes"
    record.save(update_fields=["notes"])
    call_command("provision_integration_templates")
    record.refresh_from_db()
    assert record.notes == "Preserve approved operator notes"
    assert ProviderConfiguration.objects.count() == 16
    assert not record.endpoints.exists()
