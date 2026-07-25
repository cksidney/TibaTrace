"""POS payment intent and settlement ledger.

Separation of concerns, deliberately kept distinct:

    DispensingEpisode.payment_state   overall commercial state of the episode.
                                      A *projection*, never set directly.
    PaymentIntent                     what must be collected, and why.
    PaymentTender                     one payment method and its allocation.
    PaymentAttempt                    one try at collecting a tender.
    PaymentSettlement                 an immutable fact: value actually received.
    PaymentProviderEvent              an inbound provider notification.
    PaymentReversal                   a controlled undo of a settlement.

Two rules shape the whole module:

1. A settlement is a financial fact. It is never edited into a different fact --
   corrections are expressed as reversals, so the ledger stays append-only.
2. Nothing infers settlement from an *attempt*. Initiating a payment says only
   that we asked; money is confirmed solely by a settlement record.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel

#: Tender types the POS can settle. Kept deliberately small -- a tender type
#: must not exist here until its settlement path does.
TENDER_TYPES = (
    ("CASH", "Cash"),
    ("CARD", "Card"),
    ("MPESA", "M-PESA"),
)

#: Providers. MANUAL covers tenders settled by a person at the till (cash, and
#: card approval references keyed in from a standalone terminal) rather than by
#: a provider API.
PROVIDER_CODES = (
    ("MANUAL", "Manual"),
    ("FAKE", "Fake provider (test/demo)"),
    ("MPESA", "M-PESA"),
)

MONEY = {"max_digits": 15, "decimal_places": 2}


class PaymentIntent(TenantConsistencyMixin, TimestampedModel):
    """What must be collected for one dispensing episode."""

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        OPEN = "OPEN", "Open"
        PARTIALLY_SETTLED = "PARTIALLY_SETTLED", "Partially settled"
        SETTLED = "SETTLED", "Settled"
        CANCELLED = "CANCELLED", "Cancelled"
        REVERSAL_PENDING = "REVERSAL_PENDING", "Reversal pending"
        REVERSED = "REVERSED", "Reversed"
        EXPIRED = "EXPIRED", "Expired"

    #: Statuses in which an intent is still collecting money.
    ACTIVE_STATUSES = frozenset(
        {"CREATED", "OPEN", "PARTIALLY_SETTLED", "REVERSAL_PENDING"}
    )

    tenant_relation_fields = ("branch", "dispensing_episode")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT, related_name="+")
    dispensing_episode = models.ForeignKey(
        "prescription.DispensingEpisode",
        on_delete=models.PROTECT,
        related_name="payment_intents",
    )
    device_id = models.CharField(max_length=128, blank=True, default="")
    register_id = models.CharField(max_length=128, blank=True, default="")

    currency = models.CharField(max_length=3, default="KES")
    amount_due = models.DecimalField(**MONEY)
    amount_settled = models.DecimalField(default=Decimal("0"), **MONEY)
    amount_reversed = models.DecimalField(default=Decimal("0"), **MONEY)

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.CREATED)
    idempotency_key = models.CharField(max_length=255)
    correlation_id = models.UUIDField(default=uuid.uuid4)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    version = models.PositiveIntegerField(default=0)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_payment_intent_idempotency"
            ),
            # At most one intent may be collecting money for an episode at a
            # time. Without this, two terminals could each open an intent and
            # both collect the full amount.
            models.UniqueConstraint(
                fields=["dispensing_episode"],
                condition=Q(status__in=["CREATED", "OPEN", "PARTIALLY_SETTLED", "REVERSAL_PENDING"]),
                name="uq_payment_intent_one_active_per_episode",
            ),
            models.CheckConstraint(condition=Q(amount_due__gte=0), name="chk_payment_intent_due_nonneg"),
            models.CheckConstraint(
                condition=Q(amount_settled__gte=0), name="chk_payment_intent_settled_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(amount_reversed__gte=0), name="chk_payment_intent_reversed_nonneg"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_payment_intent_status"),
        ]

    def __str__(self):
        return f"Intent {self.currency} {self.amount_due} [{self.status}]"

    @property
    def effective_settled(self) -> Decimal:
        """Settled value net of reversals -- what actually counts as collected."""
        return self.amount_settled - self.amount_reversed

    @property
    def amount_remaining(self) -> Decimal:
        return max(Decimal("0"), self.amount_due - self.effective_settled)


class PaymentTender(TenantConsistencyMixin, TimestampedModel):
    """One payment method carrying part (or all) of an intent."""

    class Status(models.TextChoices):
        ALLOCATED = "ALLOCATED", "Allocated"
        PENDING = "PENDING", "Pending"
        PARTIALLY_SETTLED = "PARTIALLY_SETTLED", "Partially settled"
        SETTLED = "SETTLED", "Settled"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        REVERSAL_PENDING = "REVERSAL_PENDING", "Reversal pending"
        REVERSED = "REVERSED", "Reversed"

    #: Tenders that still count toward the intent's allocation.
    LIVE_STATUSES = frozenset(
        {"ALLOCATED", "PENDING", "PARTIALLY_SETTLED", "SETTLED", "REVERSAL_PENDING"}
    )

    tenant_relation_fields = ("payment_intent",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    payment_intent = models.ForeignKey(
        PaymentIntent, on_delete=models.PROTECT, related_name="tenders"
    )
    tender_type = models.CharField(max_length=20, choices=TENDER_TYPES)
    provider = models.CharField(max_length=20, choices=PROVIDER_CODES, default="MANUAL")

    allocated_amount = models.DecimalField(**MONEY)
    settled_amount = models.DecimalField(default=Decimal("0"), **MONEY)
    reversed_amount = models.DecimalField(default=Decimal("0"), **MONEY)

    # Cash-only bookkeeping. change_due is derived once, at settlement, from
    # authoritative values -- never recomputed on read.
    cash_received = models.DecimalField(null=True, blank=True, **MONEY)
    change_due = models.DecimalField(null=True, blank=True, **MONEY)
    shift = models.ForeignKey(
        "prescription.PosShiftRecord",
        on_delete=models.PROTECT,
        related_name="payment_tenders",
        null=True,
        blank=True,
    )
    register_id = models.CharField(max_length=128, blank=True, default="")

    external_reference = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ALLOCATED)
    idempotency_key = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_payment_tender_idempotency"
            ),
            # A provider reference identifies one real-world payment. Reusing it
            # would double-count the same money.
            models.UniqueConstraint(
                fields=["tenant", "provider", "external_reference"],
                condition=~Q(external_reference=""),
                name="uq_payment_tender_provider_reference",
            ),
            models.CheckConstraint(
                condition=Q(allocated_amount__gt=0), name="chk_payment_tender_allocated_positive"
            ),
            models.CheckConstraint(
                condition=Q(settled_amount__gte=0), name="chk_payment_tender_settled_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(reversed_amount__gte=0), name="chk_payment_tender_reversed_nonneg"
            ),
        ]

    def __str__(self):
        return f"{self.tender_type} {self.allocated_amount} [{self.status}]"

    @property
    def effective_settled(self) -> Decimal:
        return self.settled_amount - self.reversed_amount


class PaymentAttempt(TenantConsistencyMixin, TimestampedModel):
    """One try at collecting a tender. Never evidence that money arrived."""

    class Status(models.TextChoices):
        STARTED = "STARTED", "Started"
        ACCEPTED = "ACCEPTED", "Accepted by provider"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        TIMED_OUT = "TIMED_OUT", "Timed out"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant_relation_fields = ("payment_tender",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    payment_tender = models.ForeignKey(
        PaymentTender, on_delete=models.PROTECT, related_name="attempts"
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CODES)
    attempt_number = models.PositiveIntegerField(default=1)

    #: Our reference, generated before we call out, so a callback that arrives
    #: before the initiation response can still be matched.
    request_reference = models.CharField(max_length=255)
    provider_reference = models.CharField(max_length=255, blank=True, default="")

    requested_amount = models.DecimalField(**MONEY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)
    request_payload_hash = models.CharField(max_length=64, blank=True, default="")
    response_payload_hash = models.CharField(max_length=64, blank=True, default="")
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_reason = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=255)
    correlation_id = models.UUIDField(default=uuid.uuid4)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_payment_attempt_idempotency"
            ),
            models.UniqueConstraint(
                fields=["tenant", "request_reference"], name="uq_payment_attempt_request_reference"
            ),
            models.CheckConstraint(
                condition=Q(requested_amount__gt=0), name="chk_payment_attempt_amount_positive"
            ),
        ]

    def __str__(self):
        return f"Attempt {self.request_reference} [{self.status}]"


class PaymentSettlement(TenantConsistencyMixin, TimestampedModel):
    """An immutable record that value was received.

    Never updated into a different financial fact: corrections are reversals.
    """

    class Source(models.TextChoices):
        CASH = "CASH", "Cash at till"
        CARD_MANUAL = "CARD_MANUAL", "Manually confirmed card approval"
        PROVIDER_EVENT = "PROVIDER_EVENT", "Provider callback"
        PROVIDER_QUERY = "PROVIDER_QUERY", "Provider status query"

    tenant_relation_fields = ("payment_tender",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    payment_tender = models.ForeignKey(
        PaymentTender, on_delete=models.PROTECT, related_name="settlements"
    )
    payment_attempt = models.ForeignKey(
        PaymentAttempt,
        on_delete=models.PROTECT,
        related_name="settlements",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="KES")
    provider_reference = models.CharField(max_length=255, blank=True, default="")
    settlement_reference = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(max_length=20, choices=Source.choices)
    settled_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=255)
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_payment_settlement_idempotency"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="chk_payment_settlement_amount_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "provider_reference"], name="ix_settlement_provider_ref"),
        ]

    def __str__(self):
        return f"Settlement {self.currency} {self.amount}"

    def save(self, *args, **kwargs):
        if (
            self.pk is not None
            and PaymentSettlement.all_objects.filter(
                pk=self.pk, tenant_id=self.tenant_id
            ).exists()
        ):
            raise ValueError(
                "PaymentSettlement is immutable; express corrections as a PaymentReversal."
            )
        return super().save(*args, **kwargs)


class PaymentProviderEvent(TenantConsistencyMixin, TimestampedModel):
    """An inbound provider notification or polled status response."""

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        AUTHENTICATED = "AUTHENTICATED", "Authenticated"
        PROCESSED = "PROCESSED", "Processed"
        DUPLICATE = "DUPLICATE", "Duplicate"
        REJECTED = "REJECTED", "Rejected"
        UNMATCHED = "UNMATCHED", "Unmatched"

    tenant_relation_fields = ()
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    provider = models.CharField(max_length=20, choices=PROVIDER_CODES)
    event_type = models.CharField(max_length=64)
    #: Provider-assigned id for this notification, when the provider supplies
    #: one. This is what makes duplicate delivery detectable.
    event_id = models.CharField(max_length=255, blank=True, default="")
    provider_reference = models.CharField(max_length=255, blank=True, default="")
    request_reference = models.CharField(max_length=255, blank=True, default="")

    payload_hash = models.CharField(max_length=64)
    authenticated = models.BooleanField(default=False)
    processing_status = models.CharField(
        max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.RECEIVED
    )
    processing_error = models.TextField(blank=True, default="")
    correlation_id = models.UUIDField(default=uuid.uuid4)
    received_at = models.DateTimeField(auto_now_add=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            # One provider event is applied at most once.
            models.UniqueConstraint(
                fields=["tenant", "provider", "event_id"],
                condition=~Q(event_id=""),
                name="uq_payment_provider_event_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "provider", "request_reference"], name="ix_provider_event_reqref"
            ),
        ]

    def __str__(self):
        return f"{self.provider} {self.event_type} [{self.processing_status}]"


class PaymentReversal(TenantConsistencyMixin, TimestampedModel):
    """A controlled undo of a prior settlement."""

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        REJECTED = "REJECTED", "Rejected"

    tenant_relation_fields = ("settlement",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    settlement = models.ForeignKey(
        PaymentSettlement, on_delete=models.PROTECT, related_name="reversals"
    )
    amount = models.DecimalField(**MONEY)
    reason = models.TextField()
    provider_reference = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    #: Separation of duties: a reversal is approved by someone other than the
    #: requester. Enforced in the service, recorded here.
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_payment_reversal_idempotency"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="chk_payment_reversal_amount_positive"
            ),
        ]

    def __str__(self):
        return f"Reversal {self.amount} [{self.status}]"
