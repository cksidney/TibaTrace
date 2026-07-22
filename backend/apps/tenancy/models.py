from django.db import models

from apps.core.models import TimestampedModel


class Tenant(TimestampedModel):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_CHOICES = ((STATUS_ACTIVE, "Active"), (STATUS_SUSPENDED, "Suspended"))

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    country_code = models.CharField(max_length=2, default="KE")
    time_zone = models.CharField(max_length=64, default="Africa/Nairobi")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "id"]

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    def __str__(self) -> str:
        return self.name
