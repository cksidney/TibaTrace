"""National Operational Notification Engine & Regulatory Expiry Engine service.

Handles notification creation, role-based channel dispatching, and automated
expiry evaluation across 9 alert threshold intervals:
  180, 90, 60, 30, 14, 7, 3, 1, 0 (Expired)

Truth label: MANUAL_INTERNAL_VERIFICATION
Escalation stops only after renewal evidence is recorded.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.audit.service import log_audit
from apps.notifications.models import (
    IntegrationNotification,
    NotificationChannel,
    NotificationEventCategory,
    NotificationOutbox,
    NotificationRolePreference,
    NotificationSeverity,
    RegulatoryExpiryTrack,
)

logger = logging.getLogger(__name__)

EXPIRY_ALERT_INTERVALS = [180, 90, 60, 30, 14, 7, 3, 1, 0]


def emit_integration_notification(
    *,
    category: str,
    severity: str,
    title: str,
    summary: str,
    tenant_id: object | None = None,
    payload: dict | None = None,
) -> IntegrationNotification:
    """Emit an operational integration notification and route to outbox channels."""
    notif = IntegrationNotification.all_objects.create(
        tenant_id=tenant_id,
        category=category,
        severity=severity,
        title=title,
        summary=summary,
        payload=payload or {},
        truth_label="MANUAL_INTERNAL_VERIFICATION",
    )

    if tenant_id:
        log_audit(
            tenant_id=tenant_id,
            action="INTEGRATION_NOTIFICATION_EMITTED",
            model_name="IntegrationNotification",
            object_id=notif.id,
            metadata={
                "category": category,
                "severity": severity,
                "truth_label": "MANUAL_INTERNAL_VERIFICATION",
            },
        )

    # Route channels based on role preferences
    prefs = NotificationRolePreference.objects.filter(category=category)
    for pref in prefs:
        for ch in pref.enabled_channels:
            if ch in (NotificationChannel.EMAIL, NotificationChannel.SMS, NotificationChannel.WHATSAPP):
                idempotency_key = f"notif-{notif.id}-{ch}-{pref.role_code}"
                if tenant_id:
                    NotificationOutbox.all_objects.get_or_create(
                        tenant_id=tenant_id,
                        idempotency_key=idempotency_key,
                        defaults={
                            "channel": ch,
                            "recipient": f"role:{pref.role_code}",
                            "template_code": f"nif_{category.lower()}",
                            "payload": {"notification_id": str(notif.id), "title": title, "summary": summary},
                            "status": "PENDING",
                        },
                    )

    return notif


def evaluate_regulatory_expiries(tenant_id: object | None = None) -> list[RegulatoryExpiryTrack]:
    """Evaluate active expiry tracks against alert intervals (180d -> 0d).

    Triggers notifications when thresholds are crossed.
    Escalation continues until is_resolved is set to True upon evidence submission.
    """
    today = timezone.localdate()
    tracks_qs = RegulatoryExpiryTrack.all_objects.filter(is_resolved=False)
    if tenant_id:
        tracks_qs = tracks_qs.filter(tenant_id=tenant_id)

    processed = []
    for track in tracks_qs:
        days_remaining = (track.expires_at - today).days

        # Determine highest crossed interval threshold
        crossed_interval = None
        for interval in EXPIRY_ALERT_INTERVALS:
            if days_remaining <= interval:
                crossed_interval = interval

        if crossed_interval is None:
            continue

        # Check if already notified for this exact or lower interval
        if track.last_notified_interval_days is not None and track.last_notified_interval_days <= crossed_interval:
            continue

        # Escalation severity assignment
        if crossed_interval <= 0:
            severity = NotificationSeverity.EMERGENCY
            category = NotificationEventCategory.PREMISES_LICENCE_EXPIRY if track.entity_type == "PREMISES_LICENCE" else NotificationEventCategory.PRACTITIONER_LICENCE_EXPIRY
            title = f"EXPIRED: {track.display_name}"
            summary = f"{track.display_name} expired on {track.expires_at}. Operational access blocked."
        elif crossed_interval <= 7:
            severity = NotificationSeverity.CRITICAL
            category = NotificationEventCategory.PREMISES_LICENCE_EXPIRY
            title = f"CRITICAL EXPIRY ({days_remaining}d): {track.display_name}"
            summary = f"{track.display_name} expires in {days_remaining} days on {track.expires_at}."
        elif crossed_interval <= 30:
            severity = NotificationSeverity.HIGH
            category = NotificationEventCategory.PREMISES_LICENCE_EXPIRY
            title = f"Expiry Warning ({days_remaining}d): {track.display_name}"
            summary = f"{track.display_name} expires in {days_remaining} days on {track.expires_at}."
        else:
            severity = NotificationSeverity.WARNING
            category = NotificationEventCategory.PREMISES_LICENCE_EXPIRY
            title = f"Upcoming Expiry ({days_remaining}d): {track.display_name}"
            summary = f"{track.display_name} expires in {days_remaining} days on {track.expires_at}."

        emit_integration_notification(
            category=category,
            severity=severity,
            title=title,
            summary=summary,
            tenant_id=track.tenant_id,
            payload={"entity_type": track.entity_type, "entity_id": track.entity_id, "days_remaining": days_remaining},
        )

        track.last_notified_interval_days = crossed_interval
        track.save(update_fields=["last_notified_interval_days", "updated_at"])
        processed.append(track)

    return processed
