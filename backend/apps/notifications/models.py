from __future__ import annotations

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
