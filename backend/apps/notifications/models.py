"""Phase 14B National Operational Notification & Regulatory Expiry Engine models.

Severity Model:
  INFO, WARNING, HIGH, CRITICAL, EMERGENCY

Delivery Channels:
  HQ_COMMAND_CENTRE, IN_APP, EMAIL, SMS (interface), WHATSAPP (interface)

Governance:
  - Role-scoped notification preferences
  - Regulatory expiry engine tracking 180d, 90d, 60d, 30d, 14d, 7d, 3d, 1d, Expired intervals
  - Escalation stops only after renewal evidence exists
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class NotificationOutbox(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="notification_outbox")
    channel = models.CharField(max_length=40)
    recipient = models.CharField(max_length=255)
    template_code = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="PENDING")
    idempotency_key = models.CharField(max_length=160)
    last_error = models.CharField(max_length=255, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], name="uq_notification_idempotency")
        ]


class NotificationSeverity(models.TextChoices):
    INFO = "INFO", "Information"
    WARNING = "WARNING", "Warning"
    HIGH = "HIGH", "High Priority"
    CRITICAL = "CRITICAL", "Critical Action Required"
    EMERGENCY = "EMERGENCY", "Emergency System Alert"


class NotificationChannel(models.TextChoices):
    HQ_COMMAND_CENTRE = "HQ_COMMAND_CENTRE", "HQ Notification Centre"
    IN_APP = "IN_APP", "In-App Banner/Alert"
    EMAIL = "EMAIL", "Email Notification"
    SMS = "SMS", "SMS Notification (Interface)"
    WHATSAPP = "WHATSAPP", "WhatsApp Notification (Interface)"


class NotificationEventCategory(models.TextChoices):
    DHA_UNAVAILABLE = "DHA_UNAVAILABLE", "DHA System Unavailable"
    PPB_UNAVAILABLE = "PPB_UNAVAILABLE", "PPB System Unavailable"
    HWR_UNAVAILABLE = "HWR_UNAVAILABLE", "DHA HWR System Unavailable"
    OAUTH_TOKEN_EXPIRY = "OAUTH_TOKEN_EXPIRY", "OAuth Token Expiry Warning"  # not-a-secret: event code
    OAUTH_REFRESH_FAILURE = "OAUTH_REFRESH_FAILURE", "OAuth Refresh Token Failure"
    TLS_CERTIFICATE_EXPIRY = "TLS_CERTIFICATE_EXPIRY", "TLS Certificate Expiry Warning"
    PROVIDER_CERTIFICATE_EXPIRY = "PROVIDER_CERTIFICATE_EXPIRY", "Provider Client Certificate Expiry"
    PREMISES_LICENCE_EXPIRY = "PREMISES_LICENCE_EXPIRY", "Premises Licence Expiry Warning"
    SUPERINTENDENT_LICENCE_EXPIRY = "SUPERINTENDENT_LICENCE_EXPIRY", "Superintendent Licence Expiry Warning"
    PRACTITIONER_LICENCE_EXPIRY = "PRACTITIONER_LICENCE_EXPIRY", "Practitioner Licence Expiry Warning"
    CONTROLLED_MEDICINE_AUTHORITY_EXPIRY = "CONTROLLED_MEDICINE_AUTHORITY_EXPIRY", "Controlled Medicine Authority Expiry"
    INTEGRATION_ACTIVATION_PENDING = "INTEGRATION_ACTIVATION_PENDING", "Integration Activation Request Pending"
    INTEGRATION_ACTIVATION_APPROVED = "INTEGRATION_ACTIVATION_APPROVED", "Integration Activation Approved"
    INTEGRATION_ACTIVATION_REJECTED = "INTEGRATION_ACTIVATION_REJECTED", "Integration Activation Rejected"
    PROVIDER_CONNECTIVITY_RESTORED = "PROVIDER_CONNECTIVITY_RESTORED", "Provider Connectivity Restored"
    CIRCUIT_BREAKER_OPENED = "CIRCUIT_BREAKER_OPENED", "Circuit Breaker Opened"
    CIRCUIT_BREAKER_CLOSED = "CIRCUIT_BREAKER_CLOSED", "Circuit Breaker Closed"
    RETRY_THRESHOLD_EXCEEDED = "RETRY_THRESHOLD_EXCEEDED", "Retry Threshold Exceeded"
    DEAD_LETTER_THRESHOLD_EXCEEDED = "DEAD_LETTER_THRESHOLD_EXCEEDED", "Dead Letter Queue Threshold Exceeded"
    REGULATORY_RECALL_ACTIVATED = "REGULATORY_RECALL_ACTIVATED", "Regulatory Recall Activated"
    REGULATORY_RECALL_ESCALATED = "REGULATORY_RECALL_ESCALATED", "Regulatory Recall Escalated"
    REGULATORY_RECALL_RELEASED = "REGULATORY_RECALL_RELEASED", "Regulatory Recall Released"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED", "Emergency Provider Kill Switch Activated"
    KILL_SWITCH_RELEASED = "KILL_SWITCH_RELEASED", "Emergency Provider Kill Switch Released"


class IntegrationNotification(TimestampedModel):
    """A governed operational notification record for national integrations."""

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="integration_notifications",
    )
    category = models.CharField(max_length=60, choices=NotificationEventCategory.choices)
    severity = models.CharField(max_length=20, choices=NotificationSeverity.choices, default=NotificationSeverity.INFO)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="read_notifications",
    )
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acknowledged_notifications",
    )
    truth_label = models.CharField(max_length=60, default="MANUAL_INTERNAL_VERIFICATION")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "severity", "-created_at"], name="ix_notif_tenant_sev"),
            models.Index(fields=["category", "-created_at"], name="ix_notif_cat_created"),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category}: {self.title}"


class NotificationRolePreference(TimestampedModel):
    """Role-scoped notification delivery preferences."""

    role_code = models.CharField(
        max_length=40,
        help_text="e.g. platform.owner, compliance.officer, tenant.admin, pharmacist",
    )
    category = models.CharField(max_length=60, choices=NotificationEventCategory.choices)
    enabled_channels = models.JSONField(
        default=list,
        help_text="List of NotificationChannel values enabled for this role & category.",
    )
    minimum_severity = models.CharField(
        max_length=20,
        choices=NotificationSeverity.choices,
        default=NotificationSeverity.INFO,
    )

    objects = models.Manager()

    class Meta:
        unique_together = [("role_code", "category")]

    def __str__(self) -> str:
        return f"Pref({self.role_code}, {self.category})"


class RegulatoryExpiryTrack(TimestampedModel):
    """Track expiry intervals for regulated entities (Premises, Practitioners, Credentials)."""

    class EntityType(models.TextChoices):
        PREMISES_LICENCE = "PREMISES_LICENCE", "Pharmacy Premises Licence"
        SUPERINTENDENT_LICENCE = "SUPERINTENDENT_LICENCE", "Superintendent Pharmacist Licence"
        PRACTITIONER_LICENCE = "PRACTITIONER_LICENCE", "Practitioner Licence"
        CONTROLLED_DRUG_AUTHORITY = "CONTROLLED_DRUG_AUTHORITY", "Controlled Medicine Authority"
        OAUTH_CREDENTIAL = "OAUTH_CREDENTIAL", "OAuth Client Secret / Key"
        PROVIDER_CERTIFICATE = "PROVIDER_CERTIFICATE", "TLS / Client Certificate"

    entity_type = models.CharField(max_length=40, choices=EntityType.choices)
    entity_id = models.CharField(max_length=100)
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="regulatory_expiry_tracks",
    )
    display_name = models.CharField(max_length=200)
    expires_at = models.DateField()
    last_notified_interval_days = models.IntegerField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_evidence_reference = models.CharField(max_length=250, blank=True)
    truth_label = models.CharField(max_length=60, default="MANUAL_INTERNAL_VERIFICATION")

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["expires_at"]
        indexes = [
            models.Index(fields=["entity_type", "expires_at"], name="ix_regexp_type_exp"),
        ]

    def __str__(self) -> str:
        return f"ExpiryTrack({self.entity_type}, {self.display_name}, exp={self.expires_at})"
