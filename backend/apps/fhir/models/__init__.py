from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class FHIRIdempotencyRecord(TimestampedModel):
    STATE_PROCESSING = "PROCESSING"
    STATE_COMPLETED = "COMPLETED"
    STATE_CHOICES = [
        (STATE_PROCESSING, "Processing"),
        (STATE_COMPLETED, "Completed"),
    ]

    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="fhir_idempotency_records",
    )
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    resource_type = models.CharField(max_length=64)
    operation = models.CharField(max_length=16)
    resource_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default=STATE_PROCESSING)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fhir_idempotency_records",
    )

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uq_fhir_idempotency_tenant_key"),
            models.CheckConstraint(
                condition=(
                    models.Q(state="PROCESSING", resource_id__isnull=True)
                    | models.Q(state="COMPLETED", resource_id__isnull=False)
                ),
                name="ck_fhir_idempotency_state_resource",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "resource_type", "resource_id"],
                name="ix_fhir_idempotency_resource",
            ),
            models.Index(fields=["tenant", "created_at"], name="ix_fhir_idempotency_created"),
        ]

    def clean(self):
        super().clean()
        if not self.tenant_id:
            raise ValidationError({"tenant": "Tenant ownership is required."})
        if self.state == self.STATE_PROCESSING and self.resource_id:
            raise ValidationError({"resource_id": "A processing request cannot reference a result."})
        if self.state == self.STATE_COMPLETED and not self.resource_id:
            raise ValidationError({"resource_id": "A completed request requires a result resource."})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.pk:
            previous = FHIRIdempotencyRecord.all_objects.filter(
                pk=self.pk,
                tenant_id=self.tenant_id,
            ).first()
            if previous and any(
                getattr(previous, field) != getattr(self, field)
                for field in ("tenant_id", "key", "request_hash", "resource_type", "operation")
            ):
                raise ValidationError("FHIR idempotency identity fields are immutable.")
        return super().save(*args, **kwargs)
