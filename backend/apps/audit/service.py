from __future__ import annotations

from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditEvent, PlatformAuditEvent
from apps.core.request_context import get_current_request_id


def log_audit(
    *, tenant_id, action: str, model_name: str, object_id: str, user_id=None, actor_id=None, metadata=None, outcome="SUCCESS"
):
    return AuditEvent.all_objects.create(
        tenant_id=tenant_id,
        actor_id=actor_id or user_id,
        action=action,
        model_name=model_name,
        object_id=str(object_id),
        correlation_id=get_current_request_id() or "",
        outcome=outcome,
        metadata=metadata or {},
    )


def log_platform_audit(*, actor_id, action, model_name, object_id, metadata=None, outcome="SUCCESS"):
    from apps.identity.models import User

    # tenant-safety: platform-audit-authority-check
    actor = User.objects.filter(pk=actor_id, is_active=True).first()
    if not actor or not (actor.is_platform_admin or actor.is_superuser):
        raise PermissionDenied("Platform audit writes require explicit platform authority.")
    return PlatformAuditEvent.objects.create(
        actor=actor,
        action=action,
        model_name=model_name,
        object_id=str(object_id),
        correlation_id=get_current_request_id() or "",
        outcome=outcome,
        metadata=metadata or {},
    )
