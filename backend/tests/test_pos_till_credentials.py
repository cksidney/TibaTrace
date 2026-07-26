"""Till Login ID + PIN credentials.

A PIN is a low-entropy secret typed in the open at a counter. These tests pin
the properties that make that acceptable: it is bounded by lockout, it cannot be
enumerated, it is never stored in the clear, and it cannot reach anything a
password is meant to guard.

Do not relax these to make sign-in smoother. Every one of them is the reason the
short credential is allowed to exist.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.identity.models import Role, User, UserRole
from apps.identity.pos_authentication import (
    PasswordRequired,
    PosSession,
    TillAuthenticationFailed,
    TillAuthenticationService,
)
from apps.identity.pos_credentials import (
    MAX_FAILED_ATTEMPTS,
    PIN_SESSION_CAPABILITIES,
    CredentialLocked,
    PinPolicyError,
    PosCredential,
    requires_password,
    validate_pin,
)
from apps.tenancy.models import Tenant


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Till Tenant", slug="till-tenant")


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Other Tenant", slug="other-tenant")


def make_operator(tenant, *, username="cashier", capabilities=None, password="system-password-1"):
    user = User.objects.create_user(
        username=f"{username}-{tenant.slug}", password=password, tenant=tenant
    )
    role = Role.objects.create(
        tenant=tenant, code=f"role-{username}", name="Till", capabilities=capabilities or []
    )
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    return user


def make_credential(tenant, user, *, login_id="07", pin="8351"):
    credential = PosCredential(tenant=tenant, user=user, login_id=login_id)
    credential.set_pin(pin)
    credential.save()
    return credential


# ─── PIN policy ──────────────────────────────────────────────────────────────


class TestPinPolicy:
    def test_accepts_a_reasonable_pin(self):
        assert validate_pin("8351") == "8351"

    @pytest.mark.parametrize("pin", ["123", "123456789", "", "   "])
    def test_rejects_wrong_length(self, pin):
        with pytest.raises(PinPolicyError):
            validate_pin(pin)

    @pytest.mark.parametrize("pin", ["abcd", "12a4", "12 4", "1.24"])
    def test_rejects_non_digits(self, pin):
        with pytest.raises(PinPolicyError):
            validate_pin(pin)

    @pytest.mark.parametrize("pin", ["0000", "1111", "9999"])
    def test_rejects_repeated_digits(self, pin):
        with pytest.raises(PinPolicyError):
            validate_pin(pin)

    @pytest.mark.parametrize("pin", ["1234", "4321", "3456", "6543"])
    def test_rejects_runs(self, pin):
        with pytest.raises(PinPolicyError):
            validate_pin(pin)

    def test_rejects_common_pins(self):
        # A default PIN is a shared PIN, and a shared PIN destroys attribution.
        with pytest.raises(PinPolicyError):
            validate_pin("123456")


# ─── storage ─────────────────────────────────────────────────────────────────


class TestPinStorage:
    def test_pin_is_never_stored_in_the_clear(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), pin="8351")
        assert "8351" not in credential.pin_hash
        assert credential.pin_hash != "8351"
        # And nothing else on the row carries it either.
        assert "8351" not in str(credential.__dict__)

    def test_pin_verifies(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), pin="8351")
        assert credential.check_pin("8351") is True
        assert credential.check_pin("8352") is False

    def test_a_credential_cannot_be_saved_without_a_pin(self, tenant):
        # Stronger than checking that a PIN-less credential rejects sign-in: the
        # row cannot exist at all, so there is no window in which a credential
        # is usable-looking but unauthenticated.
        from django.core.exceptions import ValidationError as DjangoValidationError

        with pytest.raises(DjangoValidationError):
            PosCredential.all_objects.create(
                tenant=tenant, user=make_operator(tenant), login_id="09", pin_hash=""
            )

    def test_an_unusable_hash_rejects_every_pin(self, tenant):
        # Defence in depth for a row that reached this state some other way --
        # a fixture, a data migration, a manual edit.
        credential = make_credential(tenant, make_operator(tenant), login_id="09")
        credential.pin_hash = "!"  # Django's marker for an unusable password.
        assert credential.check_pin("") is False
        assert credential.check_pin("8351") is False

    def test_an_issued_pin_must_be_changed(self, tenant):
        credential = PosCredential(tenant=tenant, user=make_operator(tenant), login_id="07")
        credential.set_pin("8351", issued=True)
        # Whoever issued it knows it.
        assert credential.must_change_pin is True

    def test_choosing_a_pin_clears_the_change_requirement(self, tenant):
        credential = make_credential(tenant, make_operator(tenant))
        assert credential.must_change_pin is False


# ─── sign-in ─────────────────────────────────────────────────────────────────


class TestSignIn:
    def test_correct_credentials_issue_a_session(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        assert session.is_active
        assert token

    def test_the_token_is_stored_hashed(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        # A session token is a bearer credential; plaintext in the table is
        # immediately usable if the table leaks.
        assert session.token_hash != token
        assert token not in session.token_hash

    def test_wrong_pin_is_refused(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        with pytest.raises(TillAuthenticationFailed):
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8352", device_id="TILL-1"
            )

    def test_unknown_login_id_fails_identically_to_a_wrong_pin(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")

        with pytest.raises(TillAuthenticationFailed) as unknown:
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="99", pin="8351", device_id="TILL-1"
            )
        with pytest.raises(TillAuthenticationFailed) as wrong_pin:
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8352", device_id="TILL-1"
            )

        # Otherwise the screen tells an attacker which Login IDs exist, and a
        # known Login ID plus four digits is a far smaller search.
        assert str(unknown.value) == str(wrong_pin.value)

    def test_a_disabled_account_does_not_announce_itself(self, tenant):
        user = make_operator(tenant)
        credential = make_credential(tenant, user, login_id="07", pin="8351")
        credential.is_active = False
        credential.save()

        with pytest.raises(TillAuthenticationFailed) as disabled:
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
            )
        assert "lock" not in str(disabled.value).lower()

    def test_a_device_identifier_is_required(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        # An unattributable session cannot be reconciled to a till at shift end.
        with pytest.raises(TillAuthenticationFailed):
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8351", device_id="  "
            )


# ─── lockout ─────────────────────────────────────────────────────────────────


class TestLockout:
    def test_repeated_failures_lock_the_credential(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")

        for _ in range(MAX_FAILED_ATTEMPTS):
            with pytest.raises(TillAuthenticationFailed):
                TillAuthenticationService.sign_in(
                    tenant=tenant, login_id="07", pin="0001", device_id="TILL-1"
                )

        # A four-digit PIN is 10,000 combinations; unthrottled that falls in
        # minutes.
        with pytest.raises(CredentialLocked):
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
            )

    def test_lockout_rejects_even_the_correct_pin(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        credential.locked_until = timezone.now() + timedelta(minutes=5)
        credential.save()

        with pytest.raises(CredentialLocked):
            TillAuthenticationService.sign_in(
                tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
            )

    def test_a_successful_sign_in_clears_the_failure_count(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")

        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            with pytest.raises(TillAuthenticationFailed):
                TillAuthenticationService.sign_in(
                    tenant=tenant, login_id="07", pin="0001", device_id="TILL-1"
                )

        TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        credential.refresh_from_db()
        assert credential.failed_attempts == 0
        assert credential.locked_until is None

    def test_an_expired_lock_stops_blocking(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        credential.locked_until = timezone.now() - timedelta(minutes=1)
        credential.failed_attempts = MAX_FAILED_ATTEMPTS
        credential.save()

        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        assert session.is_active

    def test_setting_a_new_pin_clears_the_lock(self, tenant):
        credential = make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        credential.locked_until = timezone.now() + timedelta(minutes=10)
        credential.failed_attempts = MAX_FAILED_ATTEMPTS
        credential.save()

        credential.set_pin("7429")
        credential.save()
        assert credential.is_locked is False


# ─── tenant isolation ────────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_the_same_login_id_may_exist_in_two_tenants(self, tenant, other_tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        make_credential(
            other_tenant, make_operator(other_tenant), login_id="07", pin="7429"
        )
        assert PosCredential.all_objects.filter(login_id="07").count() == 2

    def test_a_credential_cannot_be_used_against_another_tenant(self, tenant, other_tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        with pytest.raises(TillAuthenticationFailed):
            TillAuthenticationService.sign_in(
                tenant=other_tenant, login_id="07", pin="8351", device_id="TILL-1"
            )

    def test_a_session_token_does_not_resolve_in_another_tenant(self, tenant, other_tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        _, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        assert TillAuthenticationService.resolve(tenant=other_tenant, token=token) is None


# ─── session lifetime ────────────────────────────────────────────────────────


class TestSessionLifetime:
    def test_a_token_resolves_to_its_session(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        assert TillAuthenticationService.resolve(tenant=tenant, token=token).pk == session.pk

    def test_an_unknown_token_resolves_to_nothing(self, tenant):
        assert TillAuthenticationService.resolve(tenant=tenant, token="made-up") is None
        assert TillAuthenticationService.resolve(tenant=tenant, token="") is None

    def test_an_idle_session_stops_resolving(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        # A till left unattended must not stay signed in waiting for a cleanup
        # job to notice.
        PosSession.all_objects.filter(pk=session.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=2)
        )
        assert TillAuthenticationService.resolve(tenant=tenant, token=token) is None

    def test_an_expired_session_stops_resolving(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        PosSession.all_objects.filter(pk=session.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert TillAuthenticationService.resolve(tenant=tenant, token=token) is None

    def test_signing_out_ends_the_session(self, tenant):
        make_credential(tenant, make_operator(tenant), login_id="07", pin="8351")
        session, token = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        TillAuthenticationService.sign_out(session=session)
        assert TillAuthenticationService.resolve(tenant=tenant, token=token) is None


# ─── what a PIN may authorise ────────────────────────────────────────────────


class TestPinScope:
    def test_till_capabilities_need_no_password(self, tenant):
        user = make_operator(tenant, capabilities=["pos.payment.collect"])
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        actor = TillAuthenticationService.authorise(
            session=session, capability="pos.payment.collect"
        )
        assert actor.pk == user.pk

    def test_a_privileged_capability_demands_the_system_password(self, tenant):
        user = make_operator(
            tenant, capabilities=["pos.clinical_findings.override_high"], password="system-pw-1"
        )
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )

        with pytest.raises(PasswordRequired):
            TillAuthenticationService.authorise(
                session=session, capability="pos.clinical_findings.override_high"
            )

    def test_the_correct_password_authorises_a_privileged_capability(self, tenant):
        user = make_operator(
            tenant, capabilities=["pos.clinical_findings.override_high"], password="system-pw-1"
        )
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        actor = TillAuthenticationService.authorise(
            session=session,
            capability="pos.clinical_findings.override_high",
            password="system-pw-1",
        )
        assert actor.pk == user.pk

    def test_a_wrong_password_is_refused(self, tenant):
        user = make_operator(
            tenant, capabilities=["pos.clinical_findings.override_high"], password="system-pw-1"
        )
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        with pytest.raises(TillAuthenticationFailed):
            TillAuthenticationService.authorise(
                session=session,
                capability="pos.clinical_findings.override_high",
                password="not-the-password",
            )

    def test_a_pin_never_grants_a_capability_the_user_lacks(self, tenant):
        # The PIN narrows what is reachable; it never widens it.
        user = make_operator(tenant, capabilities=["dispensing.read"])
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        with pytest.raises(PermissionDenied):
            TillAuthenticationService.authorise(
                session=session, capability="pos.payment.collect"
            )

    def test_an_unclassified_capability_is_treated_as_privileged(self):
        # Forgetting to classify one must fail closed.
        assert requires_password("some.capability.nobody.classified") is True

    def test_no_override_or_administrative_capability_is_reachable_by_pin(self):
        for capability in PIN_SESSION_CAPABILITIES:
            assert "override" not in capability
            assert "admin" not in capability
            assert "configuration" not in capability
            assert "refund" not in capability

    def test_an_expired_session_authorises_nothing(self, tenant):
        user = make_operator(tenant, capabilities=["pos.payment.collect"])
        make_credential(tenant, user, login_id="07", pin="8351")
        session, _ = TillAuthenticationService.sign_in(
            tenant=tenant, login_id="07", pin="8351", device_id="TILL-1"
        )
        session.end("SIGNED_OUT")
        with pytest.raises(TillAuthenticationFailed):
            TillAuthenticationService.authorise(
                session=session, capability="pos.payment.collect"
            )
