"""Till sign-in and session issuance.

The service owns three properties the model deliberately does not:

**A wrong Login ID and a wrong PIN are indistinguishable.** Both spend the same
work and return the same failure. Otherwise the response tells an attacker which
Login IDs exist, and a valid Login ID plus a four-digit PIN is a much smaller
search than both together.

**Failures are recorded outside the caller's transaction.** A lockout that rolls
back with the request it was raised in is not a lockout.

**A PIN session is scoped, not merely authenticated.** `authorise()` is the gate
every till write goes through, and it refuses anything outside
PIN_SESSION_CAPABILITIES with an error that names the system password as the
remedy, so an operator is told what to do rather than concluding the terminal is
broken.
"""
from __future__ import annotations

import secrets

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

from .pos_credentials import (
    SESSION_ABSOLUTE_TIMEOUT,
    SESSION_IDLE_TIMEOUT,
    CredentialLocked,
    PosCredential,
    requires_password,
)

#: Work spent on a failed sign-in where the Login ID does not exist, so the
#: response time does not distinguish it from a real credential with a wrong
#: PIN. Hashing a throwaway value is the cheapest honest way to do this.
_DECOY_HASH_INPUT = "pos-credential-timing-equaliser"


class TillAuthenticationFailed(PermissionDenied):
    """Sign-in refused.

    Carries no detail about which half was wrong. The message is what an
    operator sees, and it must not become an oracle.
    """

    def __init__(self, message: str = "Login ID or PIN is incorrect.") -> None:
        super().__init__(message)


class PasswordRequired(PermissionDenied):
    """The action needs the system password, not the till PIN."""

    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(
            f"{capability} requires your system password. A till PIN cannot authorise it."
        )


class PosSession(TenantConsistencyMixin, TimestampedModel):
    """An authenticated till session.

    The token is stored hashed. A session token is a bearer credential: if the
    table leaks, plaintext tokens are immediately usable, whereas hashes are
    not.
    """

    tenant_relation_fields = ("credential",)

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_sessions"
    )
    credential = models.ForeignKey(
        PosCredential, on_delete=models.CASCADE, related_name="sessions"
    )
    token_hash = models.CharField(max_length=255, unique=True)
    device_id = models.CharField(max_length=120)
    register_id = models.CharField(max_length=120, blank=True, default="")
    location = models.ForeignKey(
        "organizations.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pos_sessions",
    )

    started_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=40, blank=True, default="")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "device_id"]),
            models.Index(fields=["token_hash"]),
        ]

    @property
    def is_active(self) -> bool:
        if self.ended_at:
            return False
        now = timezone.now()
        if self.expires_at <= now:
            return False
        # Idle expiry is enforced on read as well as on write, so a session left
        # open on an unattended till stops being usable without needing a job to
        # come along and close it.
        return self.last_seen_at + SESSION_IDLE_TIMEOUT > now

    def end(self, reason: str) -> None:
        self.ended_at = timezone.now()
        self.end_reason = reason
        self.save(update_fields=["ended_at", "end_reason", "updated_at"])


def _hash_token(token: str) -> str:
    # A session token is high-entropy, so a single SHA-256 is sufficient and
    # keeps verification cheap. PINs get a slow hash; tokens do not need one.
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TillAuthenticationService:
    """Sign an operator in at a till."""

    @staticmethod
    def sign_in(*, tenant, login_id: str, pin: str, device_id: str, register_id: str = "", location=None):
        """Verify Login ID and PIN, and issue a session.

        Returns (session, plaintext_token). The plaintext token is returned once
        and never stored.
        """
        login_id = str(login_id or "").strip()
        device_id = str(device_id or "").strip()
        if not device_id:
            # An unattributable session cannot be reconciled to a till at shift
            # end, so it is refused rather than defaulted.
            raise TillAuthenticationFailed("A device identifier is required.")

        credential = (
            PosCredential.all_objects.select_related("user")
            .filter(tenant=tenant, login_id=login_id)
            .first()
        )

        if credential is None:
            # Spend comparable work, then fail identically to a wrong PIN.
            make_password(_DECOY_HASH_INPUT)
            raise TillAuthenticationFailed()

        if credential.is_locked:
            raise CredentialLocked(
                "This Login ID is locked after repeated failed attempts. "
                "A supervisor must unlock it."
            )

        if not credential.is_active or not credential.user.is_active:
            # Same message as a bad PIN: whether an account exists but is
            # disabled is not something a sign-in screen should disclose.
            raise TillAuthenticationFailed()

        if not credential.check_pin(pin):
            # Recorded in its own transaction so the count survives the caller
            # rolling back.
            with transaction.atomic():
                credential.record_failure()
            raise TillAuthenticationFailed()

        credential.record_success()

        token = secrets.token_urlsafe(48)
        now = timezone.now()
        session = PosSession.all_objects.create(
            tenant=tenant,
            credential=credential,
            token_hash=_hash_token(token),
            device_id=device_id,
            register_id=str(register_id or ""),
            location=location,
            started_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_ABSOLUTE_TIMEOUT,
        )
        return session, token

    @staticmethod
    def resolve(*, tenant, token: str):
        """Return the live session for a token, or None.

        Touches `last_seen_at` so idle expiry measures inactivity rather than
        age.
        """
        if not token:
            return None
        session = (
            PosSession.all_objects.select_related("credential__user")
            .filter(tenant=tenant, token_hash=_hash_token(token))
            .first()
        )
        if session is None or not session.is_active:
            return None
        session.last_seen_at = timezone.now()
        session.save(update_fields=["last_seen_at", "updated_at"])
        return session

    @staticmethod
    def sign_out(*, session, reason: str = "SIGNED_OUT") -> None:
        session.end(reason)

    @staticmethod
    def authorise(*, session, capability: str, password: str | None = None):
        """Authorise a capability for a till session, returning the actor.

        Two independent checks, in this order:

        1. Is this capability within a PIN session's reach at all? If not, the
           operator's system password must be supplied and verified here.
        2. Does the operator actually hold the capability? A PIN never grants a
           capability the user does not have -- it only limits which of their
           capabilities are reachable from a till.
        """
        if session is None or not session.is_active:
            raise TillAuthenticationFailed("The till session has expired. Sign in again.")

        user = session.credential.user

        if requires_password(capability):
            if not password:
                raise PasswordRequired(capability)
            if not user.check_password(password):
                # Not a PIN failure, so it does not feed the PIN lockout
                # counter; Django's own auth throttling covers passwords.
                raise TillAuthenticationFailed("System password is incorrect.")

        if not user.has_capability(capability, tenant_id=session.tenant_id):
            raise PermissionDenied(f"Capability {capability} is required.")

        return user
