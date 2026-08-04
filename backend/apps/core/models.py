from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.tenant_context import get_current_tenant_id


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StrictTenantQuerySet(models.QuerySet):
    @staticmethod
    def _tenant_id(tenant: Any) -> Any:
        tenant_id = getattr(tenant, "pk", tenant)
        if not tenant_id:
            raise ValueError("A tenant is required for this query.")
        return tenant_id

    def for_tenant(self, tenant: Any):
        return self.filter(tenant_id=self._tenant_id(tenant))

    def get_for_tenant(self, tenant: Any, **lookup: Any):
        return self.for_tenant(tenant).get(**lookup)

    def visible_to(self, auth_context: Any):
        tenant_id = getattr(auth_context, "tenant_id", None)
        if tenant_id is None:
            tenant_id = getattr(getattr(auth_context, "tenant", None), "pk", None)
        return self.for_tenant(tenant_id)


class StrictTenantManager(models.Manager):
    def _base_queryset(self) -> StrictTenantQuerySet:
        return StrictTenantQuerySet(self.model, using=self._db)

    def get_queryset(self) -> StrictTenantQuerySet:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            return self._base_queryset().none()
        return self._base_queryset().for_tenant(tenant_id)

    def for_tenant(self, tenant: Any) -> StrictTenantQuerySet:
        return self._base_queryset().for_tenant(tenant)

    def get_for_tenant(self, tenant: Any, **lookup: Any):
        return self.for_tenant(tenant).get(**lookup)

    def visible_to(self, auth_context: Any) -> StrictTenantQuerySet:
        return self._base_queryset().visible_to(auth_context)


class TenantScopedModel(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not self.tenant_id:
            raise ValidationError({"tenant": "Tenant ownership is required."})


class TenantConsistencyMixin:
    tenant_relation_fields: tuple[str, ...] = ()

    def clean(self):
        super().clean()
        if not getattr(self, "tenant_id", None):
            raise ValidationError({"tenant": "Tenant ownership is required."})
        errors = {}
        for field_name in self.tenant_relation_fields:
            related = getattr(self, field_name, None)
            rel_tenant = getattr(related, "tenant_id", None)
            if related is not None and rel_tenant is not None and str(rel_tenant) != str(self.tenant_id):
                errors[field_name] = "Related record belongs to a different tenant."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
