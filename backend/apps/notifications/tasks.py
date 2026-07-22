from celery import shared_task
from django.utils import timezone

from apps.audit.service import log_audit
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.notifications.models import NotificationOutbox
from apps.tenancy.models import Tenant


@shared_task
def process_notification(notification_id: str, tenant_id: str):
    if not tenant_id:
        raise ValueError("Explicit tenant context is required.")
    token = set_current_tenant_id(tenant_id)
    try:
        notification = NotificationOutbox.all_objects.filter(id=notification_id, tenant_id=tenant_id).first()
        if not notification:
            if Tenant.objects.filter(id=tenant_id).exists():
                log_audit(
                    tenant_id=tenant_id,
                    action="BACKGROUND_JOB_DENIED",
                    model_name="NotificationOutbox",
                    object_id=notification_id,
                    outcome="FAILED",
                    metadata={"reason": "NOTIFICATION_OUTSIDE_TENANT_OR_MISSING"},
                )
            raise ValueError("Notification is unavailable in the supplied tenant.")
        # Phase 2 provides an outbox boundary only; no external transport is called.
        try:
            notification.status = "READY"
            notification.save(update_fields=["status", "updated_at"])
            return str(notification.id)
        except Exception as exc:
            NotificationOutbox.all_objects.filter(id=notification_id, tenant_id=tenant_id).update(
                status="FAILED", last_error=str(exc)[:255], updated_at=timezone.now()
            )
            log_audit(
                tenant_id=tenant_id,
                action="BACKGROUND_JOB_FAILED",
                model_name="NotificationOutbox",
                object_id=notification_id,
                outcome="FAILED",
                metadata={"error_type": type(exc).__name__},
            )
            raise
    finally:
        reset_current_tenant_id(token)
