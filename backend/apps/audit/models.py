from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class AuditEvent(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="audit_events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    action = models.CharField(max_length=120)
    model_name = models.CharField(max_length=120)
    object_id = models.CharField(max_length=160)
    correlation_id = models.CharField(max_length=160, blank=True)
    outcome = models.CharField(max_length=40, default="SUCCESS")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "model_name", "object_id"], name="ix_audit_object"),
            models.Index(fields=["tenant", "created_at"], name="ix_audit_created"),
        ]

    def save(self, *args, **kwargs):
        # tenant-safety: immutable-existence-check
        if self.pk and AuditEvent.all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit events are immutable.")
        if not self.tenant_id:
            raise ValidationError({"tenant": "Audit events require explicit tenant ownership."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events cannot be deleted through the application.")
