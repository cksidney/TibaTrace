"""Maker/checker B2B publication on the existing price-list and event models.

Published lists are immutable through the API. Review binds the exact draft
contents; editing a reviewed draft invalidates its decision without rewriting
the append-only review trail. Existing active lists remain active (no inferred
retrospective approvals), but future changes require a new draft.
"""
import hashlib
import json
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.service import log_audit
from apps.identity.models import User
from apps.sales.models import PriceList, PriceListEntry
from apps.tenancy.models import Tenant
from apps.workflows.models import DomainEvent
from apps.workflows.service import emit_event

KIND = "B2B_PRICE_GOVERNANCE"


def require(actor, tenant_id, capability):
    if not actor or not actor.has_capability(capability, tenant_id=tenant_id):
        raise PermissionDenied(f"Capability {capability} is required.")


def draft_content(price_list):
    values = {field: str(getattr(price_list, field)) for field in (
        "code", "name", "currency", "effective_from", "effective_to", "is_default",
    )}
    values["entries"] = [[str(getattr(row, field)) for field in (
        "pk", "sku_id", "unit_price", "minimum_quantity", "effective_from", "effective_to", "is_active",
    )] for row in PriceListEntry.all_objects.filter(tenant_id=price_list.tenant_id, price_list=price_list).order_by("pk")]
    return values


def fingerprint(price_list):
    return hashlib.sha256(json.dumps(draft_content(price_list), sort_keys=True).encode()).hexdigest()


def review_state(price_list):
    if price_list.status != "DRAFT":
        return {"state": price_list.status, "content_hash": "", "submission_id": None, "approved_by": None}
    current = fingerprint(price_list)
    latest = DomainEvent.all_objects.filter(tenant_id=price_list.tenant_id, aggregate_type=KIND,
        aggregate_id=str(price_list.pk)).order_by("-created_at", "-pk").first()
    state = "DRAFT"
    if latest and latest.payload.get("content_hash") == current:
        state = {"B2B_PRICE_SUBMITTED": "SUBMITTED", "B2B_PRICE_APPROVED": "APPROVED",
                 "B2B_PRICE_REJECTED": "REJECTED"}.get(latest.event_type, "DRAFT")
    return {"state": state, "content_hash": current,
            "submission_id": latest.payload.get("submission_id") if latest and state != "DRAFT" else None,
            "approved_by": latest.payload.get("actor_id") if state == "APPROVED" else None}


def validate_draft(price_list):
    if price_list.status != "DRAFT":
        raise ValidationError("Published or archived commercial prices are immutable. Create a new draft list.")
    if price_list.effective_to and price_list.effective_to < price_list.effective_from:
        raise ValidationError("Price list end date must not precede its start date.")
    if price_list.effective_to and price_list.effective_to < timezone.localdate():
        raise ValidationError("An expired list cannot be submitted or published.")
    entries = list(PriceListEntry.all_objects.filter(tenant_id=price_list.tenant_id, price_list=price_list).select_related("sku"))
    active = [entry for entry in entries if entry.is_active]
    if not active:
        raise ValidationError("Add at least one active, governed SKU price before review.")
    for entry in entries:
        if str(entry.sku.tenant_id) != str(price_list.tenant_id):
            raise ValidationError("A commercial entry belongs to another tenant's SKU.")
        if entry.unit_price <= 0 or entry.minimum_quantity <= 0:
            raise ValidationError("Price and quantity break must be positive. Free supply requires a separate governed exemption.")
        if entry.effective_to and entry.effective_to < entry.effective_from:
            raise ValidationError("Entry end date must not precede its start date.")
    viable = [entry for entry in active if (not entry.effective_to or entry.effective_to >= max(price_list.effective_from, timezone.localdate()))
              and (not price_list.effective_to or entry.effective_from <= price_list.effective_to)]
    if not viable:
        raise ValidationError("No active entry covers the list's current or future effective period.")
    previous = {}
    for entry in sorted(active, key=lambda row: (str(row.sku_id), row.minimum_quantity, row.effective_from)):
        group = (entry.sku_id, entry.minimum_quantity)
        if group in previous and entry.effective_from <= previous[group]:
            raise ValidationError("Overlapping entries for the same SKU and quantity break are ambiguous.")
        previous[group] = entry.effective_to or date.max


class CommercialPriceGovernanceService:
    @staticmethod
    @transaction.atomic
    def run(*, price_list, actor, operation, idempotency_key, expected_content_hash, reason):
        if not isinstance(operation, str):
            raise ValidationError("Choose a named commercial pricing command.")
        capability = {"submit": "pricing.manage", "approve": "pricing.commercial.approve",
                      "reject": "pricing.commercial.approve", "publish": "pricing.commercial.publish"}.get(operation)
        if not capability:
            raise ValidationError("Unknown commercial pricing command.")
        require(actor, price_list.tenant_id, capability)
        # Tenant anchor also serialises conflicting default-list publications.
        Tenant.objects.select_for_update().get(pk=price_list.tenant_id)
        locked = PriceList.all_objects.select_for_update().get(pk=price_list.pk, tenant_id=price_list.tenant_id)
        key = str(idempotency_key or "").strip()
        reason = str(reason or "").strip()
        if not key or len(key) > 128 or not reason or len(reason) > 1000:
            raise ValidationError("A retry key (maximum 128 characters) and specific reason (maximum 1000 characters) are required.")
        request_hash = hashlib.sha256(json.dumps([operation, expected_content_hash, reason, str(actor.pk)]).encode()).hexdigest()
        history = DomainEvent.all_objects.filter(tenant_id=locked.tenant_id, aggregate_type=KIND, aggregate_id=str(locked.pk))
        previous = history.filter(payload__idempotency_key=key).first()
        if previous:
            if previous.payload.get("request_hash") != request_hash:
                raise ValidationError("This retry key belongs to different command details or another actor.")
            return locked
        validate_draft(locked)
        content_hash = fingerprint(locked)
        if expected_content_hash != content_hash:
            raise ValidationError("Prices changed since you opened the draft. Refresh and review the actual contents.")
        state = review_state(locked)
        submission_id = state["submission_id"]
        if operation == "submit":
            submission_id = key
        elif operation in {"approve", "reject"}:
            if state["state"] != "SUBMITTED":
                raise ValidationError("Submit the exact draft contents before independent review.")
            submitted = history.filter(event_type="B2B_PRICE_SUBMITTED", payload__submission_id=submission_id).first()
            entry_ids = list(PriceListEntry.all_objects.filter(tenant_id=locked.tenant_id, price_list=locked).values_list("pk", flat=True))
            contributors = {str(value) for value in AuditEvent.all_objects.filter(tenant_id=locked.tenant_id,
                action="B2B_PRICE_CHANGED").filter(Q(object_id=str(locked.pk)) | Q(object_id__in=[str(value) for value in entry_ids])).values_list("actor_id", flat=True)}
            if str(actor.pk) == submitted.payload["actor_id"] or str(actor.pk) in contributors:
                raise ValidationError("Independent review must be performed by someone who did not submit or edit this list.")
        elif operation == "publish":
            if state["state"] != "APPROVED":
                raise ValidationError("Publication requires independent approval of these exact contents.")
            approver = User.objects.filter(pk=state["approved_by"], is_active=True).first()
            require(approver, locked.tenant_id, "pricing.commercial.approve")
            if locked.is_default:
                competing = PriceList.all_objects.filter(tenant_id=locked.tenant_id, status="ACTIVE", is_default=True).exclude(pk=locked.pk)
                if locked.effective_to:
                    competing = competing.filter(effective_from__lte=locked.effective_to)
                competing = competing.filter(Q(effective_to__isnull=True) | Q(effective_to__gte=locked.effective_from))
                if competing.exists():
                    raise ValidationError("Another default active list covers this period. Archive it explicitly or choose non-overlapping dates.")
            locked.status = "ACTIVE"
            locked.save(update_fields=["status", "updated_at"])
        event_type = {"submit": "B2B_PRICE_SUBMITTED", "approve": "B2B_PRICE_APPROVED", "reject": "B2B_PRICE_REJECTED", "publish": "B2B_PRICE_PUBLISHED"}[operation]
        emit_event(tenant_id=locked.tenant_id, aggregate_type=KIND, aggregate_id=str(locked.pk), event_type=event_type,
            payload={"actor_id": str(actor.pk), "reason": reason, "content_hash": content_hash,
                     "reviewed_contents": draft_content(locked),
                     "submission_id": submission_id, "idempotency_key": key, "request_hash": request_hash})
        log_audit(tenant_id=locked.tenant_id, actor_id=actor.pk, action=event_type, model_name="sales.PriceList",
                  object_id=locked.pk, metadata={"reason": reason, "content_hash": content_hash, "submission_id": submission_id})
        return locked

    @staticmethod
    @transaction.atomic
    def clone(*, price_list, actor, code, name, effective_from, effective_to, is_default, reason, idempotency_key):
        require(actor, price_list.tenant_id, "pricing.manage")
        Tenant.objects.select_for_update().get(pk=price_list.tenant_id)
        source = PriceList.all_objects.select_for_update().get(pk=price_list.pk, tenant_id=price_list.tenant_id)
        if not reason or not idempotency_key or len(idempotency_key) > 128:
            raise ValidationError("A reason and retry-safe command key are required.")
        payload = [code, name, str(effective_from), str(effective_to), is_default, reason, str(actor.pk)]
        request_hash = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        previous = DomainEvent.all_objects.filter(tenant_id=source.tenant_id, aggregate_type=KIND,
            aggregate_id=str(source.pk), event_type="B2B_PRICE_DRAFT_CLONED", payload__idempotency_key=idempotency_key).first()
        if previous:
            if previous.payload["request_hash"] != request_hash:
                raise ValidationError("This retry key belongs to different draft details.")
            return PriceList.all_objects.get(tenant_id=source.tenant_id, pk=previous.payload["draft_id"])
        if PriceList.all_objects.filter(tenant_id=source.tenant_id, code__iexact=code).exists():
            raise ValidationError("Choose a unique code for this new draft list.")
        if effective_to and effective_to < effective_from:
            raise ValidationError("Draft end date must not precede its start date.")
        draft = PriceList.all_objects.create(tenant_id=source.tenant_id, code=code, name=name,
            currency=source.currency, effective_from=effective_from, effective_to=effective_to, is_default=is_default)
        for row in PriceListEntry.all_objects.filter(tenant_id=source.tenant_id, price_list=source).order_by("pk"):
            PriceListEntry.all_objects.create(tenant_id=source.tenant_id, price_list=draft, sku_id=row.sku_id,
                unit_price=row.unit_price, minimum_quantity=row.minimum_quantity, effective_from=row.effective_from,
                effective_to=row.effective_to, is_active=row.is_active)
        emit_event(tenant_id=source.tenant_id, aggregate_type=KIND, aggregate_id=str(source.pk), event_type="B2B_PRICE_DRAFT_CLONED",
            payload={"actor_id": str(actor.pk), "draft_id": str(draft.pk), "idempotency_key": idempotency_key, "request_hash": request_hash})
        log_audit(tenant_id=draft.tenant_id, actor_id=actor.pk, action="B2B_PRICE_CHANGED", model_name="sales.PriceList",
            object_id=draft.pk, metadata={"reason": reason, "cloned_from": str(source.pk), "draft_contents": draft_content(draft)})
        return draft

    @staticmethod
    @transaction.atomic
    def archive(*, price_list, actor, reason):
        require(actor, price_list.tenant_id, "pricing.commercial.publish")
        if not str(reason or "").strip():
            raise ValidationError("Explain the deliberate archive; assigned customers may need a replacement list.")
        Tenant.objects.select_for_update().get(pk=price_list.tenant_id)
        locked = PriceList.all_objects.select_for_update().get(pk=price_list.pk, tenant_id=price_list.tenant_id)
        if locked.status == "ARCHIVED":
            return locked
        locked.status = "ARCHIVED"
        locked.save(update_fields=["status", "updated_at"])
        log_audit(tenant_id=locked.tenant_id, actor_id=actor.pk, action="B2B_PRICE_ARCHIVED", model_name="sales.PriceList",
                  object_id=locked.pk, metadata={"reason": str(reason).strip()[:1000]})
        return locked
