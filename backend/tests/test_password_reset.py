"""Self-service password reset.

Same posture as sign-in: the forgot endpoint must not reveal whether an account
exists, must not echo the password, and must only expose reset secrets when
DEBUG is on (local HQ without mail infrastructure).
"""
import pytest
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.tenancy.models import Tenant

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "fresh-battery-horse-staple"


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Reset Tenant", slug="reset-tenant")


@pytest.fixture
def user(tenant):
    return User.objects.create_user(
        username="reset-user",
        email="reset-user@example.com",
        password=PASSWORD,
        tenant=tenant,
        must_change_password=True,
    )


@pytest.fixture(autouse=True)
def clear_throttle_history():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client(db):
    return APIClient()


def forgot(client, **payload):
    return client.post("/api/identity/password/forgot/", payload, format="json")


def reset(client, **payload):
    return client.post("/api/identity/password/reset/", payload, format="json")


def make_token(user):
    return (
        urlsafe_base64_encode(force_bytes(user.pk)),
        PasswordResetTokenGenerator().make_token(user),
    )


class TestPasswordForgot:
    def test_known_username_returns_generic_success(self, client, user, settings):
        settings.DEBUG = False
        response = forgot(client, username="reset-user")
        assert response.status_code == 200
        body = response.json()
        assert "if an account matches" in body["detail"].lower()
        assert "dev_reset_token" not in body
        assert "dev_reset_uid" not in body

    def test_unknown_identity_returns_the_same_message(self, client, user, settings):
        settings.DEBUG = False
        known = forgot(client, username="reset-user").json()["detail"]
        unknown = forgot(client, username="nobody-here").json()["detail"]
        assert known == unknown

    def test_email_lookup_works(self, client, user, settings):
        settings.DEBUG = False
        assert forgot(client, email="reset-user@example.com").status_code == 200

    def test_debug_returns_dev_reset_secrets(self, client, user, settings):
        settings.DEBUG = True
        body = forgot(client, username="reset-user").json()
        assert body["dev_reset_uid"]
        assert body["dev_reset_token"]
        assert PasswordResetTokenGenerator().check_token(user, body["dev_reset_token"])

    def test_missing_identity_is_rejected(self, client, db):
        assert forgot(client).status_code == 400


class TestPasswordResetConfirm:
    def test_valid_token_sets_password_and_clears_must_change(self, client, user):
        uid, token = make_token(user)
        response = reset(client, uid=uid, token=token, password=NEW_PASSWORD)
        assert response.status_code == 200

        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)
        assert user.must_change_password is False

    def test_invalid_token_is_refused(self, client, user):
        uid, _token = make_token(user)
        response = reset(client, uid=uid, token="not-a-real-token", password=NEW_PASSWORD)
        assert response.status_code == 400
        user.refresh_from_db()
        assert user.check_password(PASSWORD)

    def test_weak_password_is_refused(self, client, user):
        uid, token = make_token(user)
        response = reset(client, uid=uid, token=token, password="short")
        assert response.status_code == 400
        user.refresh_from_db()
        assert user.check_password(PASSWORD)

    def test_the_new_password_is_not_echoed(self, client, user):
        uid, token = make_token(user)
        body = reset(client, uid=uid, token=token, password=NEW_PASSWORD).json()
        assert NEW_PASSWORD not in str(body)


class TestPasswordResetThrottleConfigured:
    def test_password_reset_throttle_is_configured(self):
        from django.conf import settings

        from apps.identity.api.session_views import PasswordResetThrottle

        assert PasswordResetThrottle.scope == "password_reset"
        assert "password_reset" in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
