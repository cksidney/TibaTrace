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
