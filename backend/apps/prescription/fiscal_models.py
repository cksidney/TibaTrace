"""Durable fiscal submission state, independent of payment and print state."""

import uuid

from django.db import models

from apps.core.models import TimestampedModel


class FiscalSubmission(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT)
    branch = models.ForeignKey("organizations.Location", on_delete=models.PROTECT)
    source_kind = models.CharField(max_length=20)
    source_id = models.UUIDField()
    invoice_number = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=24, default="NOT_CONFIGURED")
    payload = models.JSONField(default=dict)
    payload_sha256 = models.CharField(max_length=64, blank=True)
    response = models.JSONField(default=dict)
    error = models.CharField(max_length=300, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "source_kind", "source_id"], name="uq_fiscal_checkout_source"),
            models.UniqueConstraint(fields=["tenant", "branch", "invoice_number"], name="uq_fiscal_branch_invoice"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).first()
            if (
                previous
                and previous.payload
                and (
                    previous.payload != self.payload
                    or previous.payload_sha256 != self.payload_sha256
                    or previous.invoice_number != self.invoice_number
                )
            ):
                from django.core.exceptions import ValidationError

                raise ValidationError("A queued fiscal invoice is immutable.")
            if (
                previous
                and previous.status == "ACCEPTED"
                and (self.status != "ACCEPTED" or self.response != previous.response)
            ):
                from django.core.exceptions import ValidationError

                raise ValidationError("An accepted fiscal receipt is immutable.")
        super().save(*args, **kwargs)
