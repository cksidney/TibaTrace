from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.identity.services import UserAdministrationService
from apps.tenancy.models import Tenant


class TenantManagementService:
    @staticmethod
    @transaction.atomic
    def create_tenant(
        *,
        name: str,
        slug: str,
        country_code: str = "KE",
        time_zone: str = "Africa/Nairobi",
        metadata: dict | None = None,
    ) -> Tenant:
        if not str(name or "").strip():
            raise ValidationError({"name": "A tenant requires a name."})
        if not str(slug or "").strip():
            raise ValidationError({"slug": "A tenant requires a slug."})
        if Tenant.objects.filter(slug=slug).exists():
            raise ValidationError({"slug": "A tenant with this slug already exists."})

        tenant = Tenant.objects.create(
            name=name.strip(),
            slug=slug.strip().lower(),
            country_code=(country_code or "KE").strip().upper(),
            time_zone=(time_zone or "Africa/Nairobi").strip(),
            metadata=metadata or {},
        )
        UserAdministrationService.ensure_default_tenant_roles(tenant_id=tenant.pk)
        return tenant

    @staticmethod
    @transaction.atomic
    def update_tenant(
        *,
        tenant: Tenant,
        name: str,
        slug: str,
        country_code: str,
        time_zone: str,
        metadata: dict | None = None,
    ) -> Tenant:
        if not str(name or "").strip():
            raise ValidationError({"name": "A tenant requires a name."})
        if not str(slug or "").strip():
            raise ValidationError({"slug": "A tenant requires a slug."})
        duplicate = Tenant.objects.exclude(pk=tenant.pk).filter(slug=slug).exists()
        if duplicate:
            raise ValidationError({"slug": "A tenant with this slug already exists."})

        tenant.name = name.strip()
        tenant.slug = slug.strip().lower()
        tenant.country_code = (country_code or "KE").strip().upper()
        tenant.time_zone = (time_zone or "Africa/Nairobi").strip()
        tenant.metadata = metadata or {}
        tenant.save(
            update_fields=[
                "name",
                "slug",
                "country_code",
                "time_zone",
                "metadata",
                "updated_at",
            ]
        )
        return tenant

    @staticmethod
    @transaction.atomic
    def suspend_tenant(*, tenant: Tenant, reason: str) -> Tenant:
        if not str(reason or "").strip():
            raise ValidationError({"reason": "Suspending a tenant requires a reason."})
        metadata = dict(tenant.metadata or {})
        metadata["suspension_reason"] = reason.strip()
        tenant.metadata = metadata
        tenant.status = Tenant.STATUS_SUSPENDED
        tenant.save(update_fields=["status", "metadata", "updated_at"])
        return tenant

    @staticmethod
    @transaction.atomic
    def activate_tenant(*, tenant: Tenant) -> Tenant:
        metadata = dict(tenant.metadata or {})
        metadata.pop("suspension_reason", None)
        tenant.metadata = metadata
        tenant.status = Tenant.STATUS_ACTIVE
        tenant.save(update_fields=["status", "metadata", "updated_at"])
        UserAdministrationService.ensure_default_tenant_roles(tenant_id=tenant.pk)
        return tenant
