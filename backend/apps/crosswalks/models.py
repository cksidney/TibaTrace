from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class LegacySystem(TimestampedModel):
    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    source_environment = models.CharField(max_length=160)
    metadata = models.JSONField(default=dict, blank=True)


class LegacyIdentifierCrosswalk(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="legacy_crosswalks")
    source_system = models.ForeignKey(LegacySystem, on_delete=models.PROTECT, related_name="crosswalks")
    source_entity_type = models.CharField(max_length=120)
    source_identifier = models.CharField(max_length=255)
    target_entity_type = models.CharField(max_length=120)
    target_uuid = models.UUIDField(null=True, blank=True)
    source_hash = models.CharField(max_length=64, blank=True)
    migrated_at = models.DateTimeField(null=True, blank=True)
    migration_batch = models.CharField(max_length=120)
    immutable_metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_system", "source_entity_type", "source_identifier"],
                name="uq_crosswalk_source_tenant",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "target_entity_type", "target_uuid"], name="ix_crosswalk_target"),
            models.Index(fields=["tenant", "migration_batch"], name="ix_crosswalk_batch"),
        ]

    def save(self, *args, **kwargs):
        # tenant-safety: immutable-existence-check
        if self.pk and LegacyIdentifierCrosswalk.all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Legacy crosswalks are immutable after creation.")
        if not self.tenant_id:
            raise ValidationError({"tenant": "Crosswalk tenant ownership is required."})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Legacy crosswalks cannot be deleted through the application.")
