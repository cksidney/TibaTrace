"""Till credentials: Login ID plus PIN.

Cashiers and attendants sign in at a till with a short Login ID and a numeric
PIN, because typing a password on a counter terminal in front of a queue is not
workable. That convenience is bought with entropy, so the PIN is deliberately
constrained to a narrow set of powers.

Two rules run through this file.

**A PIN is not a password.** A four-to-six digit PIN has at most a million
combinations, and is entered in the open where it can be watched. It therefore
authorises till operation and nothing else. Anything outside
PIN_SESSION_CAPABILITIES -- price overrides, refunds, clinical overrides, user
administration, configuration -- requires the operator's system password, even
though the same person holds both. `requires_password()` is the single place
that decides.

**Brute force must be bounded.** A million combinations falls in minutes to an
unthrottled loop. Failures are counted and the credential locks. The lock is on
the credential, not the session, so it survives a client restart.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.hashers import check_password, is_password_usable, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

#: Minimum PIN length. Four digits is 10,000 combinations, which only holds up
#: because of the lockout below; anything shorter does not hold up at all.
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8

#: Failures before the credential locks, and for how long.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

#: How long a till session may run before the PIN must be entered again.
SESSION_IDLE_TIMEOUT = timedelta(minutes=20)
SESSION_ABSOLUTE_TIMEOUT = timedelta(hours=12)

#: What a PIN-authenticated session may do. An allowlist, so a capability added
#: elsewhere is outside a PIN session's reach until somebody deliberately puts
#: it here.
PIN_SESSION_CAPABILITIES: frozenset[str] = frozenset(
    {
        "dispensing.read",
        "dispensing.queue.view",
        "pos.episode.view",
        "pos.payment.collect",
        "pos.counselling.record",
        "pos.collection.confirm",
        "pos.label.print",
        "clinical.pharmacist_review.request",
    }
)

#: PINs that are not secrets. Rejected outright rather than merely discouraged:
#: a default PIN is a shared PIN, and a shared PIN destroys attribution.
FORBIDDEN_PINS: frozenset[str] = frozenset(
    {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
     "1234", "4321", "0123", "1230", "12345", "123456", "654321", "000000", "111111"}
)


class PinPolicyError(ValidationError):
    """A proposed PIN does not meet policy."""


class CredentialLocked(PermissionDenied):
    """Too many failed attempts."""


def validate_pin(pin: str) -> str:
    """Check a candidate PIN against policy, returning it normalised."""
    pin = str(pin or "").strip()

    if not pin.isdigit():
        raise PinPolicyError("A PIN must contain digits only.")
    if not MIN_PIN_LENGTH <= len(pin) <= MAX_PIN_LENGTH:
        raise PinPolicyError(f"A PIN must be {MIN_PIN_LENGTH} to {MAX_PIN_LENGTH} digits.")
    if pin in FORBIDDEN_PINS:
        raise PinPolicyError("That PIN is too common to be used.")
    if len(set(pin)) == 1:
        raise PinPolicyError("A PIN must not be a single repeated digit.")
    if _is_sequential(pin):
        raise PinPolicyError("A PIN must not be a run of consecutive digits.")
    return pin


def _is_sequential(pin: str) -> bool:
    ascending = all(int(b) - int(a) == 1 for a, b in zip(pin, pin[1:]))
    descending = all(int(a) - int(b) == 1 for a, b in zip(pin, pin[1:]))
    return ascending or descending


def requires_password(capability: str) -> bool:
    """Whether this capability needs the system password rather than a PIN.

    The default is True. A capability nobody has classified is treated as
    privileged, so forgetting to classify one fails closed.
    """
    return capability not in PIN_SESSION_CAPABILITIES


class PosCredential(TenantConsistencyMixin, TimestampedModel):
    """A till Login ID and PIN belonging to an existing user.

    Deliberately not a separate identity. The operator is the same User the
    clinical and payment services already check capabilities against, so a PIN
    sign-in produces a real actor with a real capability set and a real audit
    trail -- rather than a second, weaker notion of who did something.
    """

    tenant_relation_fields = ("user",)

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="pos_credentials"
    )
    user = models.OneToOneField(
        "identity.User", on_delete=models.CASCADE, related_name="pos_credential"
    )
    #: Short, operator-typed, and unique only within a tenant. Two pharmacies
    #: may both have a cashier "07".
    login_id = models.CharField(max_length=32)
    pin_hash = models.CharField(max_length=255)
    pin_set_at = models.DateTimeField(null=True, blank=True)
    #: Set when an administrator issues a PIN, cleared when the operator picks
    #: their own. An issued PIN is known to whoever issued it.
    must_change_pin = models.BooleanField(default=True)

    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "login_id"], name="uq_pos_credential_tenant_login"
            )
        ]
        indexes = [models.Index(fields=["tenant", "login_id"])]

    def __str__(self) -> str:
        return f"{self.login_id} ({self.tenant_id})"

    # ------------------------------------------------------------------ lock

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def set_pin(self, pin: str, *, issued: bool = False) -> None:
        """Set the PIN. Always hashed; the plaintext is never persisted."""
        validated = validate_pin(pin)
        self.pin_hash = make_password(validated)
        self.pin_set_at = timezone.now()
        self.must_change_pin = issued
        # A new PIN clears the lock: the credential holder has demonstrably
        # been through an authorised path to get here.
        self.failed_attempts = 0
        self.locked_until = None

    def check_pin(self, pin: str) -> bool:
        """Verify a PIN. Does not record the attempt -- the service does that.

        Returns False rather than raising for an unusable hash, so a credential
        with no PIN set behaves like a wrong PIN instead of an error the caller
        might treat differently and thereby leak.
        """
        if not self.pin_hash or not is_password_usable(self.pin_hash):
            return False
        return check_password(str(pin or ""), self.pin_hash)

    def record_failure(self) -> None:
        self.failed_attempts += 1
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
            self.locked_until = timezone.now() + LOCKOUT_DURATION
        self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])

    def record_success(self) -> None:
        self.failed_attempts = 0
        self.locked_until = None
        self.last_used_at = timezone.now()
        self.save(
            update_fields=["failed_attempts", "locked_until", "last_used_at", "updated_at"]
        )
