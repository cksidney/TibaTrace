"""First-login password changes must keep the browser session usable."""

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent, PlatformAuditEvent
from apps.identity.models import User
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db

PASSWORD = "Temporary-Pass-56382!"
NEW_PASSWORD = "New-Secure-Pass-773921!"
SESSION_PATH = "/api/identity/session/"
CHANGE_PATH = "/api/identity/password/change/"


@pytest.fixture(autouse=True)
def clear_throttle_history():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(params=["tenant", "tenant_platform", "platform"])
def user(request):
    tenant = None
    if request.param != "platform":
        tenant = Tenant.objects.create(name="Password Change Tenant", slug="password-change-tenant")
    return User.objects.create_user(
        username="password-change-user",
        password=PASSWORD,
        tenant=tenant,
        is_platform_admin=request.param != "tenant",
        must_change_password=True,
    )


def sign_in(user):
    client = APIClient(enforce_csrf_checks=True)
    csrf_token = client.get(SESSION_PATH).json()["csrf_token"]
    response = client.post(
        SESSION_PATH,
        {"username": user.username, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert response.status_code == 200, response.content
    assert response.json()["user"]["must_change_password"] is True
    return client, response.json()["csrf_token"]


def test_first_login_password_change_preserves_session_and_audits(user):
    client, csrf_token = sign_in(user)
    other_client, _ = sign_in(user)
    assert client.get("/api/hq/workspace/").json()["code"] == "password_change_required"

    response = client.post(
        CHANGE_PATH,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_X_REQUEST_ID="password-change-regression",
    )
    assert response.status_code == 200, response.content
    assert PASSWORD not in str(response.json())
    assert NEW_PASSWORD not in str(response.json())
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert not user.must_change_password

    session = client.get(SESSION_PATH).json()
    assert session["authenticated"] is True
    assert session["user"]["must_change_password"] is False
    assert client.get("/api/hq/workspace/").status_code == 200
    assert other_client.get(SESSION_PATH).json()["authenticated"] is False

    if user.tenant_id:
        event = AuditEvent.all_objects.get(action="SELF_PASSWORD_CHANGED")
        assert event.tenant_id == user.tenant_id
        assert not PlatformAuditEvent.objects.exists()
    else:
        event = PlatformAuditEvent.objects.get(action="SELF_PASSWORD_CHANGED")
        assert not AuditEvent.all_objects.exists()
    assert event.actor_id == user.pk
    assert event.object_id == str(user.pk)
    assert event.correlation_id == "password-change-regression"
    assert event.metadata == {}

    # The rotated token in the response must also work for the next mutation.
    assert client.delete(SESSION_PATH, HTTP_X_CSRFTOKEN=response.json()["csrf_token"]).status_code == 200


@pytest.mark.parametrize(
    ("current_password", "new_password"),
    [("incorrect-current", NEW_PASSWORD), (PASSWORD, "short"), (PASSWORD, "123456789012"), (PASSWORD, PASSWORD)],
)
def test_refused_change_keeps_temporary_password_gate_and_session(user, current_password, new_password):
    client, csrf_token = sign_in(user)
    response = client.post(
        CHANGE_PATH,
        {"current_password": current_password, "new_password": new_password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert response.status_code == 400
    assert current_password not in str(response.json())
    assert new_password not in str(response.json())
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert user.must_change_password
    assert client.get(SESSION_PATH).json()["authenticated"] is True
    assert client.get("/api/hq/workspace/").json()["code"] == "password_change_required"
    assert not AuditEvent.all_objects.exists()
    assert not PlatformAuditEvent.objects.exists()


def test_password_change_requires_csrf(user):
    client, _ = sign_in(user)
    response = client.post(
        CHANGE_PATH, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json",
    )
    assert response.status_code == 403
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert user.must_change_password


def test_audit_failure_rolls_back_password_without_breaking_session(user, monkeypatch):
    from apps.audit import service

    client, csrf_token = sign_in(user)

    def refuse_audit(**kwargs):
        raise ValidationError("The password change could not be audited.")

    with monkeypatch.context() as patch:
        patch.setattr(service, "log_audit", refuse_audit)
        patch.setattr(service, "log_platform_audit", refuse_audit)
        response = client.post(
            CHANGE_PATH,
            {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
    assert response.status_code == 400
    assert response.json()["detail"] == ["The password change could not be audited."]
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert user.must_change_password
    assert client.get(SESSION_PATH).json()["authenticated"] is True
    assert not AuditEvent.all_objects.exists()
    assert not PlatformAuditEvent.objects.exists()

    # A retry with the same browser session and current password succeeds.
    response = client.post(
        CHANGE_PATH,
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert response.status_code == 200, response.content
