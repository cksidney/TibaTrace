import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.platform.client_version import evaluate_client_version
from apps.platform.models import PosRelease
from apps.tenancy.models import Tenant


DIGEST = "a" * 64


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="POS Version Tenant", slug="pos-version-tenant")


@pytest.fixture
def user(tenant):
    return User.objects.create_user(
        username="pos-version-user",
        password="version-password-long-enough",
        tenant=tenant,
    )


def publish_release(*, minimum_supported_build=0):
    return PosRelease.objects.create(
        platform=PosRelease.Platform.WINDOWS,
        version="1.0.0",
        build_number=100,
        object_key="releases/windows/1.0.0.msix",
        size_bytes=1_024,
        sha256=DIGEST,
        minimum_supported_build=minimum_supported_build,
        operations_impact="Align clinical and cash workflows.",
        is_published=True,
    )


@pytest.mark.django_db
def test_evaluate_client_version_reports_available_advisory_update():
    publish_release(minimum_supported_build=0)

    result = evaluate_client_version(
        platform="WINDOWS",
        client_version="0.9.0",
        client_build=90,
    )

    assert result.update_available is True
    assert result.update_required is False
    assert result.latest_build == 100


@pytest.mark.django_db
def test_evaluate_client_version_reports_required_update_below_floor():
    publish_release(minimum_supported_build=95)

    result = evaluate_client_version(
        platform="WINDOWS",
        client_version="0.8.0",
        client_build=90,
    )

    assert result.update_available is True
    assert result.update_required is True


@pytest.mark.django_db
def test_client_version_endpoint_requires_authentication_and_returns_payload(user):
    anonymous = APIClient().get(
        "/api/pos/client-version/",
        {"platform": "WINDOWS", "version": "0.9.0", "build_number": 90},
    )
    assert anonymous.status_code in (401, 403)

    publish_release()
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(
        "/api/pos/client-version/",
        {"platform": "WINDOWS", "version": "0.9.0", "build_number": 90},
    )

    assert response.status_code == 200
    assert response.data["latest_version"] == "1.0.0"
    assert response.data["latest_build"] == 100
    assert response.data["update_available"] is True
    assert response.data["update_required"] is False


@pytest.mark.django_db
def test_mutating_pos_action_is_blocked_when_client_build_is_below_floor(
    tenant, user
):
    publish_release(minimum_supported_build=95)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/pos/clinical-screening/evaluate/",
        {},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
        HTTP_X_POS_CLIENT_PLATFORM="WINDOWS",
        HTTP_X_POS_CLIENT_VERSION="0.8.0",
        HTTP_X_POS_CLIENT_BUILD="90",
    )

    assert response.status_code == 426
    assert response.data["code"] == "POS_CLIENT_UPDATE_REQUIRED"
