"""Regulatory alert and product recall domain models.

Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED

This module governs the ingestion, matching, tenant quarantine, and release of
regulatory product safety alerts and recalls. It does NOT connect to the PPB
alert feed; all alerts are ingested manually by the Platform Owner compliance team.

Key entities:
  RegulatoryAlert: A global safety alert or recall notice.
  RegulatoryAlertVersion: Immutable version history for each alert.
  RegulatoryMatchCandidate: A candidate product match for an alert (confidence-tiered).
  RegulatoryTenantImpact: The impact of an alert on a specific tenant.
  RegulatoryAction: An action taken by a tenant in response to an impact.
  RegulatoryEvidence: Immutable evidence record for an action.
  RegulatoryClosure: The formal closure of an alert for a tenant.

Confidence tiers:
  GTIN_EXACT: Matched by GS1 GTIN (highest confidence).
  PPB_REGISTRATION_EXACT: Matched by PPB registration number.
  PRODUCT_MANUFACTURER_MATCH: Matched by product name + manufacturer (review required).
  BATCH_NUMBER_MATCH: Matched by batch number.
  MANUAL_REVIEW: Flagged for manual review (lowest automated confidence).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import StrictTenantManager, TimestampedModel


class AlertSeverity(models.TextChoices):
    CRITICAL = "CRITICAL", "Critical safety recall"
    HIGH = "HIGH", "High priority alert"
    MEDIUM = "MEDIUM", "Medium priority alert"
    LOW = "LOW", "Low priority / informational"


class AlertStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    RESOLVED = "RESOLVED", "Resolved"
    WITHDRAWN = "WITHDRAWN", "Withdrawn by regulator"
    SUPERSEDED = "SUPERSEDED", "Superseded by newer alert"


class MatchConfidenceTier(models.TextChoices):
    GTIN_EXACT = "GTIN_EXACT", "GS1 GTIN exact match"
    PPB_REGISTRATION_EXACT = "PPB_REGISTRATION_EXACT", "PPB registration number exact match"
    PRODUCT_MANUFACTURER_MATCH = "PRODUCT_MANUFACTURER_MATCH", "Product + manufacturer match (review required)"
    BATCH_NUMBER_MATCH = "BATCH_NUMBER_MATCH", "Batch number match"
    MANUAL_REVIEW = "MANUAL_REVIEW", "Manual review required"


class RegulatoryAlert(TimestampedModel):
    """A global regulatory safety alert or product recall.

    Global records: not tenant-scoped at this level. Tenant impact is
    captured in RegulatoryTenantImpact.

    Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED
    All alerts are ingested manually until a live PPB alert feed is activated.
    """

    alert_reference = models.CharField(
        max_length=100,
        unique=True,
        help_text="PPB or regulator-assigned reference number.",
    )
    title = models.CharField(max_length=300)
    severity = models.CharField(max_length=20, choices=AlertSeverity.choices)
    status = models.CharField(
        max_length=20, choices=AlertStatus.choices, default=AlertStatus.DRAFT
    )
    #: Which regulator issued this alert.
    issuing_regulator = models.CharField(max_length=80, default="PPB")
    #: Date the regulator issued the alert (may differ from our ingestion date).
    regulator_issue_date = models.DateField(null=True, blank=True)
    #: Product identification fields for matching.
    ppb_registration_number = models.CharField(max_length=80, blank=True)
    gtin = models.CharField(max_length=14, blank=True)
    product_name = models.CharField(max_length=300, blank=True)
    manufacturer_name = models.CharField(max_length=200, blank=True)
    affected_batches = models.JSONField(
        default=list,
        help_text="List of batch number strings.",
    )
    #: Full alert description and safety information.
    description = models.TextField(blank=True)
    recommended_action = models.TextField(blank=True)
    truth_label = models.CharField(
        max_length=60,
        default="LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED",
    )
    ingested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ingested_regulatory_alerts",
    )
    ingested_at = models.DateTimeField(default=timezone.now)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activated_regulatory_alerts",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-ingested_at"]
        indexes = [
            models.Index(fields=["status", "-ingested_at"], name="ix_regalert_status"),
            models.Index(fields=["ppb_registration_number"], name="ix_regalert_ppb_reg"),
            models.Index(fields=["gtin"], name="ix_regalert_gtin"),
        ]

    def __str__(self) -> str:
        return f"RegulatoryAlert({self.alert_reference}: {self.title[:50]})"


class RegulatoryAlertVersion(TimestampedModel):
    """Immutable version history for a RegulatoryAlert."""

    alert = models.ForeignKey(
        RegulatoryAlert,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="regulatory_alert_versions",
    )
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("alert", "version_number")]
        ordering = ["-version_number"]


class RegulatoryMatchCandidate(TimestampedModel):
    """A candidate product match for a regulatory alert, with confidence tier."""

    alert = models.ForeignKey(
        RegulatoryAlert,
        on_delete=models.CASCADE,
        related_name="match_candidates",
    )
    #: The global medicine or tenant stock item matched.
    medicine_code = models.CharField(max_length=120, blank=True)
    ppb_registration_number = models.CharField(max_length=80, blank=True)
    gtin = models.CharField(max_length=14, blank=True)
    batch_number = models.CharField(max_length=80, blank=True)
    confidence_tier = models.CharField(
        max_length=40,
        choices=MatchConfidenceTier.choices,
        default=MatchConfidenceTier.MANUAL_REVIEW,
    )
    requires_manual_review = models.BooleanField(default=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_match_candidates",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    is_confirmed = models.BooleanField(null=True)

    class Meta:
        ordering = ["confidence_tier", "-created_at"]


class RegulatoryTenantImpact(TimestampedModel):
    """The impact of a regulatory alert on a specific tenant.

    When an alert is activated and a match is confirmed, tenant impacts are
    created and stock is automatically quarantined (blocking POS sales,
    transfers, and reservations).
    """

    class ImpactState(models.TextChoices):
        PENDING = "PENDING", "Pending assessment"
        QUARANTINED = "QUARANTINED", "Stock quarantined"
        UNDER_REVIEW = "UNDER_REVIEW", "Under compliance review"
        RESOLVED = "RESOLVED", "Resolved"
        RELEASED = "RELEASED", "Released (regulator withdrawal confirmed)"
        NOT_AFFECTED = "NOT_AFFECTED", "Not affected"

    alert = models.ForeignKey(
        RegulatoryAlert,
        on_delete=models.CASCADE,
        related_name="tenant_impacts",
    )
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="regulatory_impacts",
    )
    state = models.CharField(
        max_length=20,
        choices=ImpactState.choices,
        default=ImpactState.PENDING,
    )
    quarantined_at = models.DateTimeField(null=True, blank=True)
    #: List of affected batch numbers for this tenant.
    affected_batches = models.JSONField(default=list)
    #: Stock item count quarantined.
    quarantined_stock_count = models.IntegerField(default=0)
    prior_dispense_trace_required = models.BooleanField(default=False)
    prior_dispense_patient_count = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        unique_together = [("alert", "tenant")]
        ordering = ["-created_at"]


class RegulatoryAction(TimestampedModel):
    """An action taken by a tenant compliance team in response to an alert impact."""

    class ActionType(models.TextChoices):
        STOCK_QUARANTINE = "STOCK_QUARANTINE", "Stock quarantined"
        PATIENT_CONTACT = "PATIENT_CONTACT", "Patient contact initiated"
        PRODUCT_RETURN = "PRODUCT_RETURN", "Product returned to supplier"
        DESTRUCTION = "DESTRUCTION", "Product destroyed"
        REGULATORY_REPORT = "REGULATORY_REPORT", "Regulatory report submitted"
        STOCK_RELEASE = "STOCK_RELEASE", "Stock released (post-clearance)"

    impact = models.ForeignKey(
        RegulatoryTenantImpact,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="regulatory_actions",
    )
    performed_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    evidence_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-performed_at"]


class RegulatoryEvidence(TimestampedModel):
    """Immutable audit evidence for a regulatory action. Never modified after creation."""

    action = models.ForeignKey(
        RegulatoryAction,
        on_delete=models.CASCADE,
        related_name="evidence_records",
    )
    evidence_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    truth_label = models.CharField(
        max_length=60,
        default="LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED",
    )
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-captured_at"]


class RegulatoryClosure(TimestampedModel):
    """Formal closure of an alert for a specific tenant.

    Requires compliance review and regulator withdrawal evidence before release.
    """

    impact = models.OneToOneField(
        RegulatoryTenantImpact,
        on_delete=models.CASCADE,
        related_name="closure",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="regulatory_closures",
    )
    closed_at = models.DateTimeField(default=timezone.now)
    regulator_withdrawal_reference = models.CharField(max_length=200, blank=True)
    compliance_review_notes = models.TextField()
    truth_label = models.CharField(
        max_length=60,
        default="LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED",
    )

    class Meta:
        ordering = ["-closed_at"]

    def __str__(self) -> str:
        return f"RegulatoryClosure(impact={self.impact_id}, closed_at={self.closed_at})"
