"""National Provider Integration Platform models.

This module governs the configuration, activation, message routing, and evidence
recording for national health system integrations:
  - DHA HIE (Health Information Exchange)
  - DHA HWR (Health Worker Registry)
  - PPB Premises Registry
  - PPB Product Register
  - PPB Regulatory Alerts
  - PPB Product Recalls

ACTIVATION GOVERNANCE:
No provider may be set to ACTIVE without Platform Owner approval. The full
activation flow is:
  REQUESTED -> UNDER_REVIEW -> SANDBOX_CONFIGURED -> SANDBOX_TESTING
  -> SANDBOX_PASSED -> SECURITY_APPROVED -> PRODUCTION_APPROVED -> ACTIVE

TRUTH LABELS:
  ADAPTER_SCAFFOLDED_NOT_CONNECTED: Interface exists but no live connection.
  NOT_CONFIGURED: Credentials have not been supplied or approved.
  DISABLED_IN_PRODUCTION: Explicitly blocked from live traffic.
  SANDBOX_EVIDENCE_ONLY: Connected in sandbox mode; not live.

CREDENTIAL SECURITY:
  Secrets are stored as encrypted reference strings, never as plaintext.
  The `ProviderCredentialReference` model stores a non-secret reference name
  (e.g. an environment variable name, a secrets-manager path) only. The actual
  secret is never stored in the database.

Self-verification, secret logging, and unapproved production activation
are strictly forbidden by the programme rules.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel


class ProviderType(models.TextChoices):
    DHA_HIE = "DHA_HIE", "DHA Health Information Exchange"
    DHA_HWR = "DHA_HWR", "DHA Health Worker Registry"
    PPB_PREMISES = "PPB_PREMISES", "PPB Premises Registry"
    PPB_PRODUCT_REGISTER = "PPB_PRODUCT_REGISTER", "PPB Product Register"
    PPB_REGULATORY_ALERTS = "PPB_REGULATORY_ALERTS", "PPB Regulatory Alerts"
    PPB_RECALLS = "PPB_RECALLS", "PPB Product Recalls"


class ProviderEnvironment(models.TextChoices):
    SANDBOX = "SANDBOX", "Sandbox / Test"
    PRODUCTION = "PRODUCTION", "Production"


class ActivationState(models.TextChoices):
    REQUESTED = "REQUESTED", "Activation requested"
    UNDER_REVIEW = "UNDER_REVIEW", "Under Platform Owner review"
    SANDBOX_CONFIGURED = "SANDBOX_CONFIGURED", "Sandbox configured"
    SANDBOX_TESTING = "SANDBOX_TESTING", "Sandbox testing in progress"
    SANDBOX_PASSED = "SANDBOX_PASSED", "Sandbox tests passed"
    SECURITY_APPROVED = "SECURITY_APPROVED", "Security review approved"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED", "Production approved by Platform Owner"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    DECOMMISSIONED = "DECOMMISSIONED", "Decommissioned"
    REJECTED = "REJECTED", "Activation rejected"


class ProviderConfiguration(TimestampedModel):
    """One configuration record per provider type per environment.

    The activation_state must reach ACTIVE (via the full Platform Owner
    approval chain) before any live traffic is sent.

    Truth label stored in `truth_label` reflects the actual operational state:
      ADAPTER_SCAFFOLDED_NOT_CONNECTED: The adapter code exists but no live
        endpoint has been approved and activated.
      SANDBOX_EVIDENCE_ONLY: Connected in sandbox; not live production.
    """

    provider_type = models.CharField(max_length=30, choices=ProviderType.choices)
    environment = models.CharField(
        max_length=20, choices=ProviderEnvironment.choices, default=ProviderEnvironment.SANDBOX
    )
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    activation_state = models.CharField(
        max_length=30, choices=ActivationState.choices, default=ActivationState.REQUESTED
    )
    truth_label = models.CharField(
        max_length=60,
        default="ADAPTER_SCAFFOLDED_NOT_CONNECTED",
        help_text=(
            "Empirical truth label for this integration. "
            "Must reflect actual operational state, not aspirational state."
        ),
    )
    #: Only writable by Platform Owner. Set at PRODUCTION_APPROVED -> ACTIVE transition.
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activated_provider_configurations",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    decommissioned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    #: Versioned configuration metadata (non-secret). e.g. timeout, retry policy, FHIR version.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("provider_type", "environment")]
        ordering = ["provider_type", "environment"]

    def __str__(self) -> str:
        return f"{self.provider_type} / {self.environment} ({self.activation_state})"

    @property
    def is_operational(self) -> bool:
        """True only when activation_state is ACTIVE.

        Any other state, including SANDBOX_PASSED, is not operational.
        This is the gating check used by adapters before sending traffic.
        """
        return self.activation_state == ActivationState.ACTIVE


class ProviderCredentialReference(TimestampedModel):
    """A non-secret reference to a credential stored in a secrets manager.

    IMPORTANT: This model stores a REFERENCE ONLY (e.g. an environment variable
    name or a secrets-manager path). The actual secret is NEVER stored in this
    database table. Storing actual secrets here is strictly forbidden.

    This allows the system to know which credentials are expected and configured
    without holding the values.
    """

    provider = models.ForeignKey(
        ProviderConfiguration,
        on_delete=models.CASCADE,
        related_name="credential_references",
    )
    credential_type = models.CharField(
        max_length=40,
        help_text="e.g. CLIENT_ID, OAUTH_ENDPOINT, TLS_CERT_PATH, ISSUER_URL",
    )
    #: A reference string: env var name, secrets manager path, or vault key.
    #: NEVER the actual secret value.
    reference = models.CharField(
        max_length=500,
        help_text="Reference name only; the actual secret is stored in the secrets manager, not here.",
    )
    is_configured = models.BooleanField(default=False)
    configured_at = models.DateTimeField(null=True, blank=True)
    configured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="configured_credential_references",
    )

    class Meta:
        unique_together = [("provider", "credential_type")]

    def __str__(self) -> str:
        return f"{self.provider.provider_type}.{self.credential_type} (ref: {self.reference})"


class ProviderEndpoint(TimestampedModel):
    """A specific endpoint URL for a provider.

    Stored separately so that endpoint URLs can be rotated without touching
    the main configuration. TLS host validation is done against `allowed_hosts`.
    """

    provider = models.ForeignKey(
        ProviderConfiguration,
        on_delete=models.CASCADE,
        related_name="endpoints",
    )
    name = models.CharField(max_length=100)
    base_url = models.URLField(max_length=500)
    #: Hosts that TLS validation will accept. Fail-closed: if empty, no connections allowed.
    allowed_hosts = models.JSONField(
        default=list,
        help_text="List of allowed hostnames for TLS validation. Empty = no connections permitted.",
    )
    is_active = models.BooleanField(default=False)

    class Meta:
        unique_together = [("provider", "name")]

    def __str__(self) -> str:
        return f"{self.provider.provider_type}.{self.name}: {self.base_url}"


class ProviderHealthSnapshot(TimestampedModel):
    """Periodic health snapshot for a provider endpoint."""

    provider = models.ForeignKey(
        ProviderConfiguration,
        on_delete=models.CASCADE,
        related_name="health_snapshots",
    )
    checked_at = models.DateTimeField(default=timezone.now)
    is_reachable = models.BooleanField()
    response_time_ms = models.IntegerField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    error_detail = models.TextField(blank=True)
    truth_label = models.CharField(max_length=60, default="ADAPTER_SCAFFOLDED_NOT_CONNECTED")

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["provider", "-checked_at"], name="ix_provider_health_ts"),
        ]


class IntegrationMessage(TimestampedModel):
    """Durable outbound or inbound integration message.

    Written before the network call; updated after. If the process crashes
    between write and update, the message is picked up by the retry worker.
    """

    class Direction(models.TextChoices):
        OUTBOUND = "OUTBOUND", "Outbound"
        INBOUND = "INBOUND", "Inbound"

    class MessageState(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_FLIGHT = "IN_FLIGHT", "In flight"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        DEAD_LETTERED = "DEAD_LETTERED", "Dead-lettered"
        CANCELLED = "CANCELLED", "Cancelled"

    provider = models.ForeignKey(
        ProviderConfiguration,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    message_type = models.CharField(max_length=80)
    state = models.CharField(
        max_length=20, choices=MessageState.choices, default=MessageState.PENDING
    )
    payload_digest = models.CharField(
        max_length=64,
        help_text="SHA-256 hex digest of the payload. Payload itself is not stored.",
    )
    correlation_id = models.CharField(max_length=100, blank=True)
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="integration_messages",
    )
    attempt_count = models.IntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "state", "-created_at"], name="ix_intmsg_provider_state"),
            models.Index(fields=["state", "next_retry_at"], name="ix_intmsg_retry"),
        ]

    def __str__(self) -> str:
        return f"IntegrationMessage({self.message_type}, {self.state})"


class IntegrationAttempt(TimestampedModel):
    """One delivery attempt for an IntegrationMessage."""

    message = models.ForeignKey(
        IntegrationMessage,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempted_at = models.DateTimeField(default=timezone.now)
    success = models.BooleanField()
    http_status = models.IntegerField(null=True, blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    error_class = models.CharField(max_length=100, blank=True)
    #: Sanitised error detail; MUST NOT contain secrets or PII.
    error_detail = models.TextField(blank=True)
    retry_after_seconds = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-attempted_at"]


class IntegrationDeadLetter(TimestampedModel):
    """A message that has exhausted all retry attempts.

    Dead-lettered messages must be reviewed manually by the Platform Owner.
    They can be replayed once the underlying issue is resolved.
    """

    message = models.OneToOneField(
        IntegrationMessage,
        on_delete=models.CASCADE,
        related_name="dead_letter",
    )
    dead_lettered_at = models.DateTimeField(default=timezone.now)
    dead_letter_reason = models.TextField()
    replayed_at = models.DateTimeField(null=True, blank=True)
    replayed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="replayed_dead_letters",
    )
    replay_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-dead_lettered_at"]


class IntegrationEvidence(TimestampedModel):
    """Immutable audit evidence for an integration event.

    Captures the outcome of a delivered message for compliance records.
    Once created, this record must never be modified.
    """

    message = models.ForeignKey(
        IntegrationMessage,
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    event_type = models.CharField(max_length=80)
    evidence_payload = models.JSONField(default=dict)
    truth_label = models.CharField(max_length=60, default="ADAPTER_SCAFFOLDED_NOT_CONNECTED")
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-captured_at"]


class ProviderActivationRequest(TimestampedModel):
    """A formal request to activate a provider for production use.

    Only the Platform Owner may approve. The full activation chain is:
      REQUESTED -> UNDER_REVIEW -> SANDBOX_CONFIGURED -> SANDBOX_TESTING
      -> SANDBOX_PASSED -> SECURITY_APPROVED -> PRODUCTION_APPROVED -> ACTIVE

    A rejected or decommissioned request cannot be reactivated; a new request
    must be submitted.
    """

    class RequestState(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        SANDBOX_CONFIGURED = "SANDBOX_CONFIGURED", "Sandbox configured"
        SANDBOX_TESTING = "SANDBOX_TESTING", "Sandbox testing"
        SANDBOX_PASSED = "SANDBOX_PASSED", "Sandbox passed"
        SECURITY_APPROVED = "SECURITY_APPROVED", "Security approved"
        PRODUCTION_APPROVED = "PRODUCTION_APPROVED", "Production approved"
        ACTIVE = "ACTIVE", "Active"
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"
        DECOMMISSIONED = "DECOMMISSIONED", "Decommissioned"

    provider = models.ForeignKey(
        ProviderConfiguration,
        on_delete=models.CASCADE,
        related_name="activation_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_activation_requests",
    )
    requested_at = models.DateTimeField(default=timezone.now)
    state = models.CharField(
        max_length=30, choices=RequestState.choices, default=RequestState.REQUESTED
    )
    justification = models.TextField()
    sandbox_evidence = models.JSONField(default=dict, blank=True)
    security_review_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"ActivationRequest({self.provider}, {self.state})"


class ProviderActivationDecision(TimestampedModel):
    """An immutable record of a Platform Owner decision on an activation request."""

    activation_request = models.ForeignKey(
        ProviderActivationRequest,
        on_delete=models.CASCADE,
        related_name="decisions",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_activation_decisions",
    )
    decided_at = models.DateTimeField(default=timezone.now)
    from_state = models.CharField(max_length=30)
    to_state = models.CharField(max_length=30)
    decision_notes = models.TextField(blank=True)
    truth_label = models.CharField(max_length=60, default="ADAPTER_SCAFFOLDED_NOT_CONNECTED")

    class Meta:
        ordering = ["-decided_at"]

    def __str__(self) -> str:
        return f"ActivationDecision({self.from_state} -> {self.to_state} by {self.decided_by})"
