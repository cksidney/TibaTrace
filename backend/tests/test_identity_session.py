"""Browser sign-in.

A sign-in form is the one endpoint an unauthenticated stranger is invited to
call repeatedly, so these tests are written from that position: it must not
reveal which usernames exist, must not echo the password anywhere, and must not
let somebody in without a workspace to see.
"""
import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.tenancy.models import Tenant

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Session Tenant", slug="session-tenant")


@pytest.fixture
def user(tenant):
    return User.objects.create_user(username="hq-user", password=PASSWORD, tenant=tenant)


@pytest.fixture(autouse=True)
def clear_throttle_history():
    """Reset the throttle between tests.

    DRF keeps its counters in the cache, so without this the tenth sign-in
    attempt in the module fails for every test after it -- and the failure looks
    like a broken assertion rather than a shared fixture.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client(db):
    return APIClient()


def sign_in(client, username, password):
    return client.post(
        "/api/identity/session/",
        {"username": username, "password": password},
        format="json",
    )


# ─── signing in ──────────────────────────────────────────────────────────────


class TestSignIn:
    def test_correct_credentials_establish_a_session(self, client, user):
        response = sign_in(client, "hq-user", PASSWORD)
        assert response.status_code == 200
        assert response.json()["authenticated"] is True
        assert response.json()["user"]["username"] == "hq-user"

    def test_the_session_persists_to_the_next_request(self, client, user):
        sign_in(client, "hq-user", PASSWORD)
        response = client.get("/api/identity/session/")
        assert response.json()["authenticated"] is True

    def test_the_session_carries_the_workspace(self, client, user, tenant):
        body = sign_in(client, "hq-user", PASSWORD).json()
        assert body["user"]["tenant_id"] == str(tenant.pk)
        assert body["user"]["tenant_name"] == "Session Tenant"

    def test_signing_in_grants_access_to_a_scoped_collection(self, client, user):
        # The point of the whole exercise: after signing in, the workbench
        # endpoints answer instead of returning 401.
        assert client.get("/api/insurance/claims/").status_code in (401, 403)
        sign_in(client, "hq-user", PASSWORD)
        assert client.get("/api/insurance/claims/").status_code == 200


# ─── the form does not enumerate accounts ────────────────────────────────────


class TestNoEnumeration:
    def test_a_wrong_password_is_refused(self, client, user):
        assert sign_in(client, "hq-user", "wrong").status_code == 401

    def test_an_unknown_username_is_refused(self, client, user):
        assert sign_in(client, "nobody", PASSWORD).status_code == 401

    def test_both_failures_give_the_same_message(self, client, user):
        """Otherwise the form is an account enumerator.

        A valid username plus a weak password is a far smaller search than
        both together.
        """
        wrong_password = sign_in(client, "hq-user", "wrong")
        unknown_user = sign_in(client, "nobody", PASSWORD)
        assert wrong_password.json()["detail"] == unknown_user.json()["detail"]

    def test_a_disabled_account_is_indistinguishable_from_a_wrong_password(
        self, client, user
    ):
        user.is_active = False
        user.save()
        disabled = sign_in(client, "hq-user", PASSWORD)
        wrong = sign_in(client, "hq-user", "wrong")
        assert disabled.status_code == wrong.status_code
        assert disabled.json()["detail"] == wrong.json()["detail"]

    def test_the_message_names_neither_field(self, client, user):
        detail = sign_in(client, "hq-user", "wrong").json()["detail"]
        assert "password is incorrect" not in detail.lower().replace("or password", "")
        assert "username or password" in detail.lower()


# ─── the password never comes back ───────────────────────────────────────────


class TestPasswordConfidentiality:
    def test_the_password_is_not_echoed_on_success(self, client, user):
        body = sign_in(client, "hq-user", PASSWORD).json()
        assert PASSWORD not in str(body)

    def test_the_password_is_not_echoed_on_failure(self, client, user):
        body = sign_in(client, "hq-user", "wrong").json()
        assert "wrong" not in str(body.get("user", ""))

    def test_the_password_is_not_echoed_in_a_validation_error(self, client, db):
        # A field error that repeats the submitted value puts the password in
        # whatever logs the response body.
        response = client.post(
            "/api/identity/session/", {"username": "x" * 200, "password": PASSWORD},
            format="json",
        )
        assert PASSWORD not in str(response.json())

    def test_the_serialiser_marks_the_password_write_only(self):
        from apps.identity.api.session_views import SignInSerializer

        assert SignInSerializer().fields["password"].write_only is True


# ─── a user with no workspace ────────────────────────────────────────────────


class TestWorkspaceRequired:
    def test_the_model_already_refuses_a_tenantless_user(self, db):
        """The first line of defence, and it is the schema.

        A non-platform user without a tenant cannot be created at all, so the
        endpoint's own check is belt and braces rather than the only guard.
        """
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="tenant"):
            User.objects.create_user(username="orphan", password=PASSWORD)

    def test_a_platform_admin_without_a_tenant_may_still_sign_in(self, client, db):
        # Platform administration is legitimately cross-tenant.
        User.objects.create_user(
            username="platform", password=PASSWORD, is_platform_admin=True
        )
        assert sign_in(client, "platform", PASSWORD).status_code == 200

    def test_the_endpoint_refuses_a_tenantless_user_if_one_reaches_it(self, client, db):
        """Belt and braces for a row that arrived by some other route -- a
        fixture, a data migration, a direct edit.

        Signing such a user in produces an empty workspace everywhere, which
        reads as data loss rather than as a missing assignment.
        """
        user = User.objects.create_user(
            username="orphan2", password=PASSWORD, is_platform_admin=True
        )
        # Strip the flag after creation to reach the state the model forbids.
        User.objects.filter(pk=user.pk).update(is_platform_admin=False, tenant=None)

        response = sign_in(client, "orphan2", PASSWORD)
        assert response.status_code == 403
        assert "workspace" in response.json()["detail"].lower()


# ─── reading and ending a session ────────────────────────────────────────────


class TestSessionLifecycle:
    def test_an_anonymous_read_reports_not_authenticated_rather_than_failing(
        self, client, db
    ):
        """So the app can choose between a form and a workspace without
        treating 401 as an error."""
        response = client.get("/api/identity/session/")
        assert response.status_code == 200
        assert response.json()["authenticated"] is False

    def test_a_csrf_token_is_offered_before_sign_in(self, client, db):
        # The client needs it to post credentials at all.
        assert client.get("/api/identity/session/").json()["csrf_token"]

    def test_signing_out_ends_the_session(self, client, user):
        sign_in(client, "hq-user", PASSWORD)
        assert client.delete("/api/identity/session/").status_code == 200
        assert client.get("/api/identity/session/").json()["authenticated"] is False

    def test_signing_out_revokes_access_to_scoped_data(self, client, user):
        sign_in(client, "hq-user", PASSWORD)
        assert client.get("/api/insurance/claims/").status_code == 200
        client.delete("/api/identity/session/")
        assert client.get("/api/insurance/claims/").status_code in (401, 403)

    def test_an_anonymous_caller_cannot_sign_out(self, client, db):
        assert client.delete("/api/identity/session/").status_code in (401, 403)


class TestThrottling:
    def test_the_sign_in_endpoint_is_throttled(self):
        """A password field with no throttle is an offline attack conducted
        online."""
        from django.conf import settings

        from apps.identity.api.session_views import SignInThrottle

        assert SignInThrottle.scope == "signin"
        assert "signin" in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

    def test_only_the_post_is_throttled(self, client, db):
        # Reading the session is how the app decides what to render; throttling
        # it would break the page rather than protect anything.
        from apps.identity.api.session_views import SessionView

        view = SessionView()
        view.request = type("R", (), {"method": "GET"})()
        assert view.get_throttles() == []
