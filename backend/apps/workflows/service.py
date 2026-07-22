from __future__ import annotations

from apps.core.request_context import get_current_request_id
from apps.workflows.models import DomainEvent


def emit_event(*, tenant_id, aggregate_type, aggregate_id, event_type, payload, auto_process=False):
    if not tenant_id:
        raise ValueError("Background and workflow events require an explicit tenant.")
    event = DomainEvent.all_objects.create(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        correlation_id=get_current_request_id() or "",
    )
    if auto_process:
        from apps.workflows.tasks import process_domain_event

        process_domain_event.delay(str(event.id), str(tenant_id))
    return event
