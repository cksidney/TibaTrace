from __future__ import annotations

from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class DomainEvent(TimestampedModel):
    STATUS_CHOICES = (("PENDING", "Pending"), ("PROCESSED", "Processed"), ("FAILED", "Failed"))
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="domain_events")
    aggregate_type = models.CharField(max_length=120)
    aggregate_id = models.UUIDField()
    event_type = models.CharField(max_length=160)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    correlation_id = models.CharField(max_length=160, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["tenant", "status", "created_at"], name="ix_domain_event_queue")]
