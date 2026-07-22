from __future__ import annotations

from celery import shared_task
from django.utils import timezone

from apps.audit.service import log_audit
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.tenancy.models import Tenant
from apps.workflows.models import DomainEvent


@shared_task(bind=True, max_retries=3)
def process_domain_event(self, event_id: str, tenant_id: str):
    if not tenant_id:
        raise ValueError("Explicit tenant context is required.")
    token = set_current_tenant_id(tenant_id)
    try:
        event = DomainEvent.all_objects.filter(id=event_id, tenant_id=tenant_id).first()
        if not event:
            if Tenant.objects.filter(id=tenant_id).exists():
                log_audit(
                    tenant_id=tenant_id,
                    action="BACKGROUND_JOB_DENIED",
                    model_name="DomainEvent",
                    object_id=event_id,
                    outcome="FAILED",
                    metadata={"reason": "EVENT_OUTSIDE_TENANT_OR_MISSING"},
                )
            raise ValueError("Domain event is unavailable in the supplied tenant.")
        try:
            event.status = "PROCESSED"
            event.processed_at = timezone.now()
            event.attempts += 1
            event.save(update_fields=["status", "processed_at", "attempts", "updated_at"])
            return str(event.id)
        except Exception as exc:
            DomainEvent.all_objects.filter(id=event_id, tenant_id=tenant_id).update(
                status="FAILED",
                attempts=event.attempts + 1,
                last_error=str(exc)[:255],
                updated_at=timezone.now(),
            )
            log_audit(
                tenant_id=tenant_id,
                action="BACKGROUND_JOB_FAILED",
                model_name="DomainEvent",
                object_id=event_id,
                outcome="FAILED",
                metadata={"error_type": type(exc).__name__},
            )
            raise
    finally:
        reset_current_tenant_id(token)
