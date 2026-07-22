from __future__ import annotations

from apps.audit.models import AuditEvent
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
