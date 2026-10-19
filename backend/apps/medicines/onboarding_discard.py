"""Discard untrusted opening drafts without deleting source or trading history."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.medicines.onboarding import assert_setup_access
from apps.medicines.onboarding_models import LegacyCatalogueImport, LegacyCatalogueItem


@transaction.atomic
def discard_import(*, batch, actor, reason, expected_items):
    assert_setup_access(actor, batch.tenant_id)
    batch = LegacyCatalogueImport.all_objects.select_for_update().get(pk=batch.pk, tenant_id=batch.tenant_id)
    rows = list(
        LegacyCatalogueItem.all_objects.select_for_update().filter(tenant_id=batch.tenant_id, import_batch=batch)
    )
    if len(rows) != expected_items or not str(reason).strip():
        raise ValidationError("Confirm the exact draft row count and reason before discarding this source.")
    if any(item.completion for item in rows):
        raise ValidationError("This source already has staged or released stock; use governed corrections instead.")
    changed = 0
    for item in rows:
        if item.review.get("discarded"):
            continue
        item.review = {
            **item.review,
            "excluded": True,
            "discarded": True,
            "discard_reason": reason,
            "discarded_at": timezone.now().isoformat(),
        }
        item.reviewed_by = actor
        item.save(update_fields=["review", "reviewed_by", "updated_at"])
        changed += 1
    if changed:
        log_audit(
            tenant_id=batch.tenant_id,
            actor_id=actor.pk,
            action="OPENING_IMPORT_DISCARDED",
            model_name="LegacyCatalogueImport",
            object_id=batch.pk,
            metadata={"rows": changed, "reason": reason},
        )
    return {"discarded": changed, "preserved_source_rows": len(rows), "saleable": False}
