"""Audited management operations for configured POS registers."""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.service import log_audit
from apps.pos_shift.business_days import require_branch_access

from .models import PosRegister, RegisterSession, ShiftReport


class PosRegisterControlService:
    @staticmethod
    @transaction.atomic
    def update_expected_float(*, tenant, register_id, actor, expected_float: Decimal, reason: str) -> PosRegister:
        if not actor or not any(
            actor.has_capability(capability, tenant_id=tenant.pk)
            for capability in ("pos.device.manage", "identity.manage", "pos.shift.manage")
        ):
            raise PermissionDenied("Register configuration requires pos.device.manage or pos.shift.manage.")

        register = (
            PosRegister.all_objects.select_for_update()
            .filter(tenant=tenant, pk=register_id)
            .first()
        )
        if register is None:
            raise ValidationError("Register not found for this tenant.")
        require_branch_access(actor, register.location_id)
        if register.state not in {"AVAILABLE", "CLOSED"}:
            raise ValidationError(f"Register {register.code} must be closed before its expected float can change.")
        if RegisterSession.all_objects.filter(
            tenant=tenant, register=register, state__in=("OPEN", "CLOSING")
        ).exists():
            raise ValidationError("Close the active register session before changing its expected float.")
        closed_sessions = RegisterSession.all_objects.filter(
            tenant=tenant, register=register, state="CLOSED"
        ).only("id")
        for session in closed_sessions:
            if not ShiftReport.all_objects.filter(
                tenant=tenant,
                register_session=session,
                report_type=ShiftReport.TYPE_Z,
            ).exists():
                raise ValidationError("Resolve every closed register session without a final Z before changing its expected float.")

        value = Decimal(expected_float)
        if value < Decimal("0.00"):
            raise ValidationError("Expected float cannot be negative.")
        reason = str(reason or "").strip()
        if len(reason) < 10:
            raise ValidationError("Enter a reason of at least 10 characters for the float change.")

        previous = register.expected_float
        register.expected_float = value
        register.save(update_fields=["expected_float", "updated_at"])
        log_audit(
            tenant_id=tenant.pk,
            actor_id=actor.pk,
            action="POS_REGISTER_EXPECTED_FLOAT_CHANGED",
            model_name="pos_shift.PosRegister",
            object_id=register.pk,
            metadata={
                "code": register.code,
                "previous_expected_float": str(previous),
                "expected_float": str(value),
                "reason": reason,
            },
        )
        return register
