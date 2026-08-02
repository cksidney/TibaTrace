"""Who a pharmacy is, and what state it is in.

`apps.tenancy` owns the `Tenant` row itself, because every tenant-scoped model in
the system points at it and moving it would rewrite most of the schema. This
module owns the *administration* of a pharmacy: its regulatory identity, its
lifecycle, and the record of who moved it between states.

The split matters. `tenancy` is infrastructure that every request touches;
pharmacy administration is a business domain with rules of its own, and mixing
them is how a licence expiry check ends up in middleware.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TimestampedModel


class PharmacyProfile(TimestampedModel):
    """The regulatory and commercial identity behind a tenant.

    A tenant row carries a name, a slug and a timezone -- enough to scope data,
    nowhere near enough to answer whether this pharmacy may legally trade. In
    Kenya that turns on a Pharmacy and Poisons Board premises licence and a named
    superintendent pharmacist, so those are columns here rather than keys in a
    metadata blob.
    """

    tenant = models.OneToOneField(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="pharmacy_profile"
    )

    # ── legal identity ───────────────────────────────────────────────────────
    #: The registered entity, which is often not the trading name on the sign.
    legal_name = models.CharField(max_length=200)
    business_registration_number = models.CharField(max_length=80, blank=True)
    kra_pin = models.CharField(max_length=40, blank=True)

    # ── regulatory ───────────────────────────────────────────────────────────
    #: Pharmacy and Poisons Board premises licence. Without a current one the
    #: premises may not dispense, which is why activation checks it.
    ppb_premises_licence_number = models.CharField(max_length=80, blank=True)
    ppb_licence_expiry = models.DateField(null=True, blank=True)
    #: Every registered premises must have a named superintendent pharmacist.
    superintendent_name = models.CharField(max_length=200, blank=True)
    superintendent_ppb_number = models.CharField(max_length=80, blank=True)

    # ── where the licence data came from ─────────────────────────────────────
    #
    # The Pharmacy and Poisons Board is the registrar; these columns are a copy
    # of its record, not the record itself. Until the PPB API exists every row
    # is MANUAL: somebody read a certificate and typed it in.
    #
    # That distinction has to be visible. A licence typed in eight months ago
    # and one confirmed with the registrar an hour ago make the same claim in
    # the same columns, and only one of them is worth much -- PPB can revoke a
    # licence without our copy changing.
    class LicenceSource(models.TextChoices):
        MANUAL = "MANUAL", "Entered by hand"
        PPB_API = "PPB_API", "Confirmed with PPB"

    licence_source = models.CharField(
        max_length=16, choices=LicenceSource.choices, default=LicenceSource.MANUAL
    )
    #: When the registrar last confirmed this licence. Null while no integration
    #: exists, which is itself the honest answer: never.
    licence_last_verified_at = models.DateTimeField(null=True, blank=True)
    #: The registrar's own response, kept for audit. A compliance question asked
    #: in a year is about what PPB said, not about what we stored.
    licence_verification_payload = models.JSONField(default=dict, blank=True)

    # ── contact ──────────────────────────────────────────────────────────────
    primary_contact_name = models.CharField(max_length=200, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=40, blank=True)

    # ── dates that matter commercially ───────────────────────────────────────
    onboarding_started_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    #: Tenant-strict by default, matching every other tenant-scoped model.
    #: Platform administration runs without tenant context, so the services here
    #: use `all_objects` with an explicit filter -- visible on the line rather
    #: than depending on a thread-local having been set.
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["legal_name"]
        indexes = [
            models.Index(fields=["ppb_licence_expiry"], name="ix_pharmacy_licence_exp"),
        ]

    def __str__(self) -> str:
        return self.legal_name or str(self.tenant)

    @property
    def licence_is_current(self) -> bool:
        """Whether the premises licence is present and unexpired.

        Absence is not currency: a pharmacy with no recorded licence is not
        treated as licensed. `localdate()` rather than the UTC date, or this
        reads wrong between midnight and 03:00 in Nairobi.
        """
        if not self.ppb_premises_licence_number or not self.ppb_licence_expiry:
            return False
        return self.ppb_licence_expiry >= timezone.localdate()

    @property
    def licence_is_registrar_confirmed(self) -> bool:
        """Whether the registrar itself confirmed this, rather than a person.

        Kept separate from `licence_is_current`, which answers the legal
        question -- is there an unexpired licence on file. This answers where
        that answer came from, and the two must not be conflated: a hand-typed
        licence can be current and wrong at the same time.
        """
        return (
            self.licence_source == self.LicenceSource.PPB_API
            and self.licence_last_verified_at is not None
        )

    @property
    def days_until_licence_expiry(self) -> int | None:
        if not self.ppb_licence_expiry:
            return None
        return (self.ppb_licence_expiry - timezone.localdate()).days

    def clean(self):
        super().clean()
        errors = {}
        if not (self.legal_name or "").strip():
            errors["legal_name"] = "A registered legal name is required."
        # A licence number without an expiry cannot be checked for currency, and
        # an expiry without a number does not identify a licence.
        has_number = bool((self.ppb_premises_licence_number or "").strip())
        has_expiry = self.ppb_licence_expiry is not None
        if has_number != has_expiry:
            errors["ppb_licence_expiry"] = (
                "A premises licence needs both a number and an expiry date, or neither."
            )
        if errors:
            raise ValidationError(errors)


class TenantLifecycleEvent(TimestampedModel):
    """Append-only record of every lifecycle transition.

    Suspending a pharmacy stops it trading, and terminating one ends the
    relationship. Those are decisions somebody made, for a reason, at a time --
    and until now none of that was recorded anywhere: the reason went into a JSON
    blob on the tenant and was overwritten by the next suspension, and the actor
    was not captured at all.
    """

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="lifecycle_events"
    )
    from_state = models.CharField(max_length=20)
    to_state = models.CharField(max_length=20)
    #: Null only for transitions made by the system rather than a person, such as
    #: a scheduled licence-expiry suspension.
    actor = models.ForeignKey(
        "identity.User", null=True, blank=True, on_delete=models.PROTECT,
        related_name="tenant_lifecycle_events",
    )
    reason = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    #: Anything worth keeping that is not a column: the licence checked at
    #: activation, the branch provisioned, and so on.
    context = models.JSONField(default=dict, blank=True)

    #: Tenant-strict by default, matching every other tenant-scoped model.
    #: Platform administration runs without tenant context, so the services here
    #: use `all_objects` with an explicit filter -- visible on the line rather
    #: than depending on a thread-local having been set.
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "-occurred_at"], name="ix_lifecycle_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant} {self.from_state} -> {self.to_state}"


class PremisesVerificationRequest(TimestampedModel):
    """A request to verify a pharmacy premises licence, submitted by a tenant admin.

    The full workflow:
      DRAFT -> SUBMITTED -> UNDER_REVIEW -> CLARIFICATION_REQUIRED -> VERIFIED
                                         -> REJECTED
                                         -> SUSPENDED (post-verification)
                                         -> REVOKED   (post-verification)
                                         -> SUPERSEDED (replaced by newer request)

    Governance:
    - A tenant admin may NOT approve their own verification request (self-verification block).
    - Only the Platform Owner or Compliance role may approve, reject, suspend, or revoke.
    - Dual approval is required for override transitions (SUSPENDED, REVOKED on an active tenant).
    - Truth label: MANUAL_INTERNAL_VERIFICATION until a live PPB API integration is confirmed.
    """

    class VerificationState(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted for review"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED", "Clarification required"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"
        REVOKED = "REVOKED", "Revoked"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    TERMINAL_STATES = {
        VerificationState.REJECTED,
        VerificationState.REVOKED,
        VerificationState.SUPERSEDED,
    }

    # Active (non-terminal, non-draft) states that grant operational access.
    VERIFIED_STATES = {VerificationState.VERIFIED}

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="premises_verification_requests",
    )
    #: The pharmacist profile whose licence is being verified.
    pharmacy_profile = models.ForeignKey(
        PharmacyProfile,
        on_delete=models.CASCADE,
        related_name="verification_requests",
    )
    state = models.CharField(
        max_length=30,
        choices=VerificationState.choices,
        default=VerificationState.DRAFT,
    )
    #: Submitted by the tenant admin.
    submitted_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="premises_verification_submissions",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    #: Reviewed by Platform Owner or Compliance role. NEVER the same person as submitted_by.
    reviewed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="premises_verification_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    #: Evidence submitted: licence image, certificate scan, notary reference, etc.
    evidence_payload = models.JSONField(default=dict, blank=True)
    #: Notes from reviewer (clarification requests, rejection reasons, etc.).
    reviewer_notes = models.TextField(blank=True)
    #: Verifier's declaration. Kept for audit.
    verifier_declaration = models.TextField(blank=True)
    #: Truth label. Reflects the true source of verification.
    #: MANUAL_INTERNAL_VERIFICATION: verified by internal compliance review, not by PPB API.
    #: DISABLED_IN_PRODUCTION: set when this request must be blocked from operational use.
    truth_label = models.CharField(
        max_length=60,
        default="MANUAL_INTERNAL_VERIFICATION",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "state", "-created_at"], name="ix_pvr_tenant_state"),
            models.Index(fields=["pharmacy_profile", "state"], name="ix_pvr_profile_state"),
        ]

    def __str__(self) -> str:
        return f"PremisesVerificationRequest({self.tenant}, {self.state})"

    def clean(self):
        super().clean()
        # Self-verification block: reviewer must differ from submitter.
        if (
            self.reviewed_by_id
            and self.submitted_by_id
            and self.reviewed_by_id == self.submitted_by_id
        ):
            raise ValidationError(
                {"reviewed_by": "The reviewer must not be the same person as the submitter (self-verification block)."}
            )


class PremisesVerificationSnapshot(TimestampedModel):
    """Immutable evidence snapshot for an approved or rejected verification request.

    Written at the point of state transition; never overwritten. A compliance
    question asked in a year is answered from the snapshot, not from the mutable
    request row.

    Truth label: MANUAL_INTERNAL_VERIFICATION (until PPB API integration is confirmed).
    """

    verification_request = models.ForeignKey(
        PremisesVerificationRequest,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="premises_verification_snapshots",
    )
    captured_state = models.CharField(max_length=30)
    #: The licence number as declared at the time of this snapshot.
    declared_licence_number = models.CharField(max_length=80, blank=True)
    declared_expiry = models.DateField(null=True, blank=True)
    declared_superintendent = models.CharField(max_length=200, blank=True)
    #: A copy of the evidence payload at the time of this snapshot.
    evidence_payload = models.JSONField(default=dict)
    actor = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="premises_verification_snapshot_actions",
    )
    reason = models.TextField(blank=True)
    truth_label = models.CharField(
        max_length=60,
        default="MANUAL_INTERNAL_VERIFICATION",
    )
    #: UTC timestamp when this snapshot was captured.
    captured_at = models.DateTimeField()

    # Snapshots are platform-wide (not strictly tenant-scoped) because they must
    # survive tenant suspension for audit purposes.
    objects = models.Manager()

    class Meta:
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["tenant", "-captured_at"], name="ix_pvs_tenant_ts"),
            models.Index(fields=["verification_request", "-captured_at"], name="ix_pvs_request_ts"),
        ]

    def __str__(self) -> str:
        return f"PremisesVerificationSnapshot({self.tenant}, {self.captured_state}, {self.captured_at})"
