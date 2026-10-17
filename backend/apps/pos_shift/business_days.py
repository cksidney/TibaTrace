"""Governed business-day lifecycle for a pharmacy branch.

Register sessions own the cash drawer. Business days own the accounting date.
They are changed separately so a branch cannot roll its date while a drawer is
still open or while any session is missing its final Z report.
"""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.organizations.models import Location

from .models import BusinessDay, PosRegister, RegisterSession, ShiftReport


def _require_manager(actor, tenant_id: str) -> None:
    if not actor or not actor.has_capability("pos.shift.manage", tenant_id=tenant_id):
        raise PermissionDenied("Capability pos.shift.manage is required to manage business days.")


def require_branch_access(actor, branch_id) -> None:
    metadata = getattr(actor, "metadata", None) or {}
    if actor and not getattr(actor, "is_superuser", False) and "branch_ids" in metadata:
        allowed = {str(value) for value in (metadata.get("branch_ids") or [])}
        if str(branch_id) not in allowed:
            raise PermissionDenied("The operator is not assigned to this branch.")


def tenant_business_date(tenant) -> date:
    try:
        return timezone.now().astimezone(ZoneInfo(tenant.time_zone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.localdate()


class BusinessDayControlService:
    @classmethod
    @transaction.atomic
    def open_day(cls, *, tenant, branch_id, actor, business_date: date | None = None) -> BusinessDay:
        _require_manager(actor, str(tenant.pk))
        if tenant.status != tenant.STATUS_ACTIVE:
            raise ValidationError("Only an active tenant can open a business day.")
        branch = (
            Location.all_objects.select_for_update()
            .select_related("organization")
            .filter(tenant=tenant, pk=branch_id, status="ACTIVE", organization__status="ACTIVE")
            .first()
        )
        if branch is None:
            raise ValidationError("Select an active branch in this tenant.")
        require_branch_access(actor, branch.pk)

        opening_date = business_date or tenant_business_date(tenant)
        if opening_date > tenant_business_date(tenant):
            raise ValidationError("A business day cannot be opened for a future date.")

        active_day = BusinessDay.all_objects.select_for_update().filter(
            tenant=tenant,
            location=branch,
            state__in=("OPEN", "REOPENED_BY_EXCEPTION"),
        ).first()
        if active_day:
            raise ValidationError(
                f"Business day {active_day.business_date} is still open for {branch.code}. Close it first."
            )

        if RegisterSession.all_objects.select_for_update().filter(
            tenant=tenant,
            register__location=branch,
            state__in=("OPEN", "CLOSING"),
        ).exists():
            raise ValidationError("Resolve every open register session at this branch before opening a new business day.")
        for session_id in RegisterSession.all_objects.filter(
            tenant=tenant,
            register__location=branch,
            state="CLOSED",
        ).values_list("pk", flat=True):
            if not ShiftReport.all_objects.filter(
                tenant=tenant,
                register_session_id=session_id,
                report_type=ShiftReport.TYPE_Z,
            ).exists():
                raise ValidationError("Resolve every closed register session without a final Z before opening a new business day.")
        if PosRegister.all_objects.filter(
            tenant=tenant,
            location=branch,
            state__in=("OPEN", "CLOSING"),
        ).exists():
            raise ValidationError("A register is still marked open at this branch. Reconcile it before opening a new business day.")

        latest_day = BusinessDay.all_objects.select_for_update().filter(
            tenant=tenant, location=branch
        ).order_by("-business_date").first()
        if latest_day and opening_date < latest_day.business_date:
            raise ValidationError("A new business day cannot be backdated before the branch's latest accounting date.")

        existing = BusinessDay.all_objects.select_for_update().filter(
            tenant=tenant, location=branch, business_date=opening_date
        ).first()
        if existing:
            if existing.state != "PLANNED":
                raise ValidationError(
                    f"Business day {opening_date} already exists in state {existing.state}."
                )
            existing.state = "OPEN"
            existing.opened_at = timezone.now()
            existing.closed_at = None
            existing.closed_by = None
            existing.save(update_fields=["state", "opened_at", "closed_at", "closed_by", "updated_at"])
            day = existing
        else:
            day = BusinessDay.all_objects.create(
                tenant=tenant,
                location=branch,
                business_date=opening_date,
                state="OPEN",
                opened_at=timezone.now(),
            )

        log_audit(
            tenant_id=tenant.pk,
            actor_id=actor.pk,
            action="POS_BUSINESS_DAY_OPENED",
            model_name="pos_shift.BusinessDay",
            object_id=day.pk,
            metadata={"branch_id": str(branch.pk), "branch_code": branch.code, "business_date": opening_date.isoformat()},
        )
        return day

    @classmethod
    @transaction.atomic
    def close_day(cls, *, tenant, business_day_id, actor, reason: str) -> BusinessDay:
        _require_manager(actor, str(tenant.pk))
        reason = str(reason or "").strip()
        if len(reason) < 10:
            raise ValidationError("Enter a business-day close reason of at least 10 characters.")

        day = (
            BusinessDay.all_objects.select_for_update()
            .select_related("location")
            .filter(tenant=tenant, pk=business_day_id)
            .first()
        )
        if day is None:
            raise ValidationError("Business day not found for this tenant.")
        require_branch_access(actor, day.location_id)
        if day.state not in {"OPEN", "REOPENED_BY_EXCEPTION"}:
            raise ValidationError(f"Business day {day.business_date} is {day.state} and cannot be closed.")

        sessions = RegisterSession.all_objects.select_for_update().filter(
            tenant=tenant, business_day=day
        )
        if sessions.filter(state__in=("OPEN", "CLOSING")).exists():
            raise ValidationError("Close every open register session through POS before closing this business day.")
        if PosRegister.all_objects.filter(
            tenant=tenant,
            location=day.location,
            state__in=("OPEN", "CLOSING"),
        ).exists():
            raise ValidationError("A register is still marked open at this branch. Reconcile its register session first.")
        for session in sessions:
            if not ShiftReport.all_objects.filter(
                tenant=tenant, register_session=session, report_type=ShiftReport.TYPE_Z
            ).exists():
                raise ValidationError(
                    f"Register session {session.pk} has no final Z report. Resolve it before closing the business day."
                )

        day.state = "CLOSED"
        day.closed_at = timezone.now()
        day.closed_by = actor
        day.save(update_fields=["state", "closed_at", "closed_by", "updated_at"])
        log_audit(
            tenant_id=tenant.pk,
            actor_id=actor.pk,
            action="POS_BUSINESS_DAY_CLOSED",
            model_name="pos_shift.BusinessDay",
            object_id=day.pk,
            metadata={
                "branch_id": str(day.location_id),
                "branch_code": day.location.code,
                "business_date": day.business_date.isoformat(),
                "reason": reason,
            },
        )
        return day
