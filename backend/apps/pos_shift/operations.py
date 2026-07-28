from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .authority import RegisterAuthorityService
from .cash_control import money
from .models import BusinessDay, CashDeclaration, CashMovement, OperatorShift, PosRegister, RegisterSession
from .reporting import ShiftReportService


def _require(actor, tenant_id, capability: str, aliases: tuple[str, ...] = ()) -> None:
    if not actor or not any(actor.has_capability(item, tenant_id=tenant_id) for item in (capability, *aliases)):
        raise PermissionDenied(f"Capability {capability} is required.")


def _denomination_total(denominations: dict[str, int] | None) -> Decimal | None:
    if not denominations:
        return None
    total = Decimal("0.00")
    for denomination, quantity in denominations.items():
        try:
            face_value = Decimal(str(denomination))
            count = int(quantity)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValidationError("Denominations must contain decimal values and whole counts.") from exc
        if face_value <= 0 or count < 0:
            raise ValidationError("Denominations must use positive values and non-negative counts.")
        total += face_value * count
    return money(total)


class RegisterOpeningService:
    @staticmethod
    @transaction.atomic
    def open(
        *,
        tenant,
        register_id,
        actor,
        device_id: str,
        opening_amount,
        denominations: dict[str, int] | None = None,
    ) -> tuple[RegisterSession, OperatorShift, CashDeclaration]:
        _require(actor, tenant.pk, "pos.register.open", ("pos.shift.manage",))
        register = (
            PosRegister.all_objects.select_for_update()
            .select_related("location")
            .filter(tenant=tenant, pk=register_id)
            .first()
        )
        if register is None:
            raise ValidationError("Register not found for this tenant.")
        if register.device_id != device_id:
            raise ValidationError("The selected register is not assigned to this device.")
        if not register.accepts_opening:
            raise ValidationError(f"Register {register.code} is {register.state} and cannot be opened.")
        if RegisterSession.all_objects.filter(register=register, state__in=["OPEN", "CLOSING"]).exists():
            raise ValidationError(f"Register {register.code} already has an active session.")

        previous = (
            RegisterSession.all_objects.select_related("business_day")
            .filter(tenant=tenant, register=register)
            .order_by("-opened_at")
            .first()
        )
        if previous and ShiftReportService.final_report(session=previous) is None:
            raise ValidationError("The previous register session has no final Z report.")

        business_day = (
            BusinessDay.all_objects.filter(
                tenant=tenant,
                location=register.location,
                state__in=["OPEN", "REOPENED_BY_EXCEPTION"],
            )
            .order_by("-business_date")
            .first()
        )
        if business_day is None or not business_day.accepts_transactions:
            raise ValidationError("No open business day is available for this register.")

        amount = money(opening_amount)
        if amount < 0:
            raise ValidationError("Opening cash cannot be negative.")
        counted = _denomination_total(denominations)
        if counted is not None and counted != amount:
            raise ValidationError("Opening denomination total does not match the declared amount.")

        session = RegisterSession.all_objects.create(
            tenant=tenant,
            register=register,
            business_day=business_day,
            opened_by=actor,
            state="OPEN",
        )
        operator_shift = OperatorShift.all_objects.create(
            tenant=tenant,
            register_session=session,
            operator=actor,
            state="OPEN",
        )
        declaration = CashDeclaration.all_objects.create(
            tenant=tenant,
            register_session=session,
            operator_shift=operator_shift,
            kind="OPENING",
            declared_amount=amount,
            denominations=denominations or {},
            currency=register.currency,
            declared_by=actor,
            attempt=1,
            confirmed_at=timezone.now(),
        )
        register.state = "OPEN"
        register.save(update_fields=["state", "updated_at"])
        return session, operator_shift, declaration


class CashDeclarationService:
    @staticmethod
    @transaction.atomic
    def declare_closing(
        *,
        tenant,
        branch,
        actor,
        device_id: str,
        declared_amount,
        denominations: dict[str, int] | None = None,
        reason: str = "",
    ) -> CashDeclaration:
        _require(actor, tenant.pk, "pos.cash.closing_declare", ("pos.shift.manage",))
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
        )
        amount = money(declared_amount)
        if amount < 0:
            raise ValidationError("Closing cash cannot be negative.")
        counted = _denomination_total(denominations)
        if counted is not None and counted != amount:
            raise ValidationError("Closing denomination total does not match the declared amount.")
        attempt = (
            CashDeclaration.all_objects.filter(
                tenant=tenant,
                register_session=authority.session,
                kind="CLOSING",
            ).aggregate(Max("attempt"))["attempt__max"]
            or 0
        ) + 1
        return CashDeclaration.all_objects.create(
            tenant=tenant,
            register_session=authority.session,
            operator_shift=authority.operator_shift,
            kind="CLOSING",
            declared_amount=amount,
            denominations=denominations or {},
            currency=authority.register.currency,
            declared_by=actor,
            attempt=attempt,
            confirmed_at=timezone.now(),
            reason=reason,
        )


class CashMovementService:
    @staticmethod
    @transaction.atomic
    def record(
        *,
        tenant,
        branch,
        actor,
        device_id: str,
        kind: str,
        amount,
        reason_code: str,
        description: str = "",
        reference: str = "",
    ) -> CashMovement:
        _require(actor, tenant.pk, "pos.cash.movement.create", ("pos.shift.manage",))
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
        )
        if kind not in dict(CashMovement.KINDS):
            raise ValidationError("Unsupported cash movement type.")
        amount = money(amount)
        if amount <= 0:
            raise ValidationError("Cash movement amount must be greater than zero.")
        if not reason_code.strip():
            raise ValidationError("A cash movement reason code is required.")
        return CashMovement.all_objects.create(
            tenant=tenant,
            register_session=authority.session,
            operator_shift=authority.operator_shift,
            kind=kind,
            amount=amount,
            currency=authority.register.currency,
            reason_code=reason_code.strip(),
            description=description.strip(),
            reference=reference.strip(),
            created_by=actor,
        )

    @staticmethod
    @transaction.atomic
    def approve(*, movement: CashMovement, actor) -> CashMovement:
        _require(actor, movement.tenant_id, "pos.cash.movement.approve")
        movement = CashMovement.all_objects.select_for_update().get(
            tenant_id=movement.tenant_id,
            pk=movement.pk,
        )
        if movement.created_by_id == actor.pk:
            raise ValidationError("A cash-movement creator cannot approve their own movement.")
        if movement.approved_at is not None:
            return movement
        movement.approved_by = actor
        movement.approved_at = timezone.now()
        movement.save(update_fields=["approved_by", "approved_at", "updated_at"])
        return movement


class OperatorShiftService:
    @staticmethod
    @transaction.atomic
    def request_handover(
        *,
        tenant,
        actor,
        device_id: str,
        operator_shift_id,
        reason: str = "",
    ) -> OperatorShift:
        _require(actor, tenant.pk, "pos.shift.handover", ("pos.shift.manage",))
        register = (
            PosRegister.all_objects.select_related("location")
            .filter(tenant=tenant, device_id=device_id)
            .first()
        )
        if register is None:
            raise ValidationError("This device is not assigned to a register.")
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=register.location,
            actor=actor,
            device_id=device_id,
        )
        if str(authority.operator_shift.pk) != str(operator_shift_id):
            raise ValidationError("The selected operator shift is not active on this device.")
        operator_shift = OperatorShift.all_objects.select_for_update().get(
            tenant=tenant,
            pk=authority.operator_shift.pk,
        )
        if operator_shift.state == "HANDOVER_REQUESTED":
            return operator_shift
        if operator_shift.state != "OPEN":
            raise ValidationError("Only an open operator shift can request handover.")
        operator_shift.state = "HANDOVER_REQUESTED"
        operator_shift.close_reason = reason.strip()
        operator_shift.save(update_fields=["state", "close_reason", "updated_at"])
        return operator_shift

    @staticmethod
    @transaction.atomic
    def cancel_handover(
        *,
        tenant,
        actor,
        device_id: str,
        operator_shift_id,
    ) -> OperatorShift:
        _require(actor, tenant.pk, "pos.shift.handover", ("pos.shift.manage",))
        operator_shift = (
            OperatorShift.all_objects.select_for_update()
            .select_related("register_session__register")
            .filter(tenant=tenant, pk=operator_shift_id, operator=actor)
            .first()
        )
        if operator_shift is None:
            raise ValidationError("The handover request is unavailable to this operator.")
        if operator_shift.register_session.register.device_id != device_id:
            raise ValidationError("The handover belongs to a different device.")
        if operator_shift.state == "OPEN":
            return operator_shift
        if operator_shift.state != "HANDOVER_REQUESTED":
            raise ValidationError("Only a pending handover can be cancelled.")
        operator_shift.state = "OPEN"
        operator_shift.close_reason = ""
        operator_shift.save(update_fields=["state", "close_reason", "updated_at"])
        return operator_shift

    @staticmethod
    @transaction.atomic
    def accept_handover(
        *,
        tenant,
        actor,
        device_id: str,
        operator_shift_id,
    ) -> tuple[OperatorShift, OperatorShift]:
        _require(actor, tenant.pk, "pos.shift.handover", ("pos.shift.manage",))
        outgoing = (
            OperatorShift.all_objects.select_for_update()
            .select_related("register_session__register", "register_session__business_day")
            .filter(tenant=tenant, pk=operator_shift_id)
            .first()
        )
        if outgoing is None:
            raise ValidationError("The requested handover was not found.")
        session = outgoing.register_session
        register = session.register
        if register.device_id != device_id:
            raise ValidationError("The handover belongs to a different device.")
        if register.state != "OPEN" or session.state != "OPEN":
            raise ValidationError("The register session is not open for handover.")
        if not session.business_day.accepts_transactions:
            raise ValidationError("The business day does not accept a handover.")
        if outgoing.state != "HANDOVER_REQUESTED":
            raise ValidationError("The operator shift is not awaiting handover.")
        if outgoing.operator_id == actor.pk:
            raise ValidationError("A handover must be accepted by a different operator.")
        if OperatorShift.all_objects.filter(
            tenant=tenant,
            register_session=session,
            operator=actor,
            state__in=["OPEN", "HANDOVER_REQUESTED"],
        ).exists():
            raise ValidationError("The accepting operator already has an active shift.")

        now = timezone.now()
        outgoing.state = "CLOSED"
        outgoing.ended_at = now
        outgoing.handed_over_to = actor
        outgoing.closed_by = actor
        outgoing.save(
            update_fields=[
                "state",
                "ended_at",
                "handed_over_to",
                "closed_by",
                "updated_at",
            ]
        )
        incoming = OperatorShift.all_objects.create(
            tenant=tenant,
            register_session=session,
            operator=actor,
            state="OPEN",
        )
        return outgoing, incoming


class RegisterReportService:
    @staticmethod
    @transaction.atomic
    def generate_x(*, tenant, branch, actor, device_id: str):
        _require(actor, tenant.pk, "pos.report.x.generate", ("pos.shift.manage",))
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
        )
        return ShiftReportService.generate_x(session=authority.session, actor=actor)

    @staticmethod
    @transaction.atomic
    def finalise_z(
        *,
        tenant,
        branch,
        actor,
        device_id: str,
        declared_amount,
        denominations: dict[str, int] | None = None,
        reason: str = "",
    ):
        _require(actor, tenant.pk, "pos.report.z.generate", ("pos.shift.manage",))
        registers = list(
            PosRegister.all_objects.select_related("location")
            .filter(tenant=tenant, device_id=device_id)
        )
        if not registers:
            raise ValidationError("This device is not assigned to a register.")
        if len(registers) != 1:
            raise ValidationError("This device has conflicting register assignments.")
        register = registers[0]
        latest_session = (
            RegisterSession.all_objects.filter(
                tenant=tenant,
                register=register,
            )
            .order_by("-opened_at")
            .first()
        )
        existing = (
            ShiftReportService.final_report(session=latest_session)
            if latest_session is not None
            else None
        )
        if existing is not None:
            return existing
        authority = RegisterAuthorityService.resolve_for_transaction(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
        )
        CashDeclarationService.declare_closing(
            tenant=tenant,
            branch=branch,
            actor=actor,
            device_id=device_id,
            declared_amount=declared_amount,
            denominations=denominations,
            reason=reason,
        )
        return ShiftReportService.finalise_z(
            session=authority.session,
            actor=actor,
            declared_cash=money(declared_amount),
            reason=reason,
        )
