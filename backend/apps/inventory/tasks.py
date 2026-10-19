"""Periodic stock maintenance: fan-out never inherits an implicit tenant."""

from zoneinfo import ZoneInfo

from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.inventory.services import ExpiryControlService, InventoryReservationService
from apps.tenancy.models import Tenant


@shared_task
def dispatch_expiry_maintenance():
    # Suspended tenants still own stock that expires. Terminated tenants are
    # preserved as historical records and require a deliberate disposal plan.
    tenant_ids = Tenant.objects.exclude(status=Tenant.STATUS_TERMINATED).order_by("pk").values_list("pk", flat=True)
    dispatched = 0
    for tenant_id in tenant_ids.iterator():
        process_tenant_expiry.delay(str(tenant_id))
        dispatched += 1
    return {"dispatched_tenants": dispatched}


@shared_task(bind=True, max_retries=3, autoretry_for=(OperationalError,), retry_backoff=True)
def process_tenant_expiry(self, tenant_id: str):
    if not tenant_id:
        raise ValueError("Explicit tenant context is required for expiry maintenance.")
    tenant = Tenant.objects.get(pk=tenant_id)
    if tenant.status == Tenant.STATUS_TERMINATED:
        return {"tenant_id": str(tenant.pk), "processed_batches": 0, "skipped": "TERMINATED"}
    token = set_current_tenant_id(tenant.pk)
    try:
        # Invalid timezone configuration fails visibly rather than applying
        # another tenant's local date silently.
        with timezone.override(ZoneInfo(tenant.time_zone)):
            count = ExpiryControlService.process_expired_batches(tenant, as_of=timezone.localdate())
            expired_reservations = InventoryReservationService.expire_due(tenant)
        return {"tenant_id": str(tenant.pk), "processed_batches": count, "expired_reservations": expired_reservations}
    finally:
        reset_current_tenant_id(token)


@shared_task
def dispatch_replenishment_planning():
    for tenant_id in Tenant.objects.filter(status=Tenant.STATUS_ACTIVE).values_list("pk", flat=True).iterator():
        plan_tenant_replenishment.delay(str(tenant_id))


@shared_task(bind=True, max_retries=3, autoretry_for=(OperationalError,), retry_backoff=True)
def plan_tenant_replenishment(self, tenant_id):
    from apps.inventory.replenishment import refresh
    tenant = Tenant.objects.get(pk=tenant_id, status=Tenant.STATUS_ACTIVE)
    with timezone.override(ZoneInfo(tenant.time_zone)):
        return {"recommendations": refresh(tenant)}
