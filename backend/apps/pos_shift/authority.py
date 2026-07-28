from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from apps.prescription.models import PosDeviceHealthRecord

from .models import BusinessDay, OperatorShift, PosRegister, RegisterSession
from .reporting import ShiftReportService, register_accepts_transactions


@dataclass(frozen=True)
class RegisterAuthority:
    register: PosRegister
    session: RegisterSession
    operator_shift: OperatorShift
    business_day: BusinessDay


class RegisterAuthorityService:
    @classmethod
    def resolve_for_transaction(cls, *, tenant, branch, actor, device_id: str) -> RegisterAuthority:
        if not device_id.strip():
            raise ValidationError("A registered POS device is required for this transaction.")
        if not actor or str(getattr(actor, "tenant_id", "")) != str(tenant.pk):
            raise ValidationError("The authenticated operator is not assigned to this tenant.")
        if str(branch.tenant_id) != str(tenant.pk):
            raise ValidationError("The transaction branch does not belong to this tenant.")

        with transaction.atomic():
            registers = list(
                PosRegister.all_objects.select_for_update()
                .select_related("location")
                .filter(tenant=tenant, device_id=device_id)
            )
            if not registers:
                raise ValidationError("This device is not assigned to a register.")
            if len(registers) != 1:
                raise ValidationError("This device has conflicting register assignments.")
            register = registers[0]
            if register.location_id != branch.pk:
                raise ValidationError("The assigned register belongs to a different branch.")
            if register.state != "OPEN":
                raise ValidationError(f"Register {register.code} is {register.state} and cannot accept transactions.")

            session = (
                RegisterSession.all_objects.select_for_update()
                .select_related("register", "business_day")
                .filter(tenant=tenant, register=register, state="OPEN")
                .order_by("-opened_at")
                .first()
            )
            if session is None:
                raise ValidationError(f"Register {register.code} has no active register session.")
            if session.business_day.location_id != branch.pk:
                raise ValidationError("The active register session belongs to a different branch.")
            if not register_accepts_transactions(session):
                raise ValidationError("The active register session does not accept transactions.")

            operator_shift = (
                OperatorShift.all_objects.select_for_update()
                .filter(
                    tenant=tenant,
                    register_session=session,
                    operator=actor,
                    state__in=["OPEN", "HANDOVER_REQUESTED"],
                )
                .order_by("-started_at")
                .first()
            )
            if operator_shift is None:
                raise ValidationError("The signed-in operator has no active shift on this register.")

            return RegisterAuthority(
                register=register,
                session=session,
                operator_shift=operator_shift,
                business_day=session.business_day,
            )

    @classmethod
    def runtime_status(cls, *, tenant, actor, device_id: str) -> dict:
        if not device_id.strip():
            return cls._unassigned("A registered POS device is required.")

        registers = list(
            PosRegister.all_objects.select_related("location").filter(tenant=tenant, device_id=device_id)
        )
        if not registers:
            return cls._unassigned("This device is not assigned to a register.")
        if len(registers) != 1:
            return cls._unassigned("This device has conflicting register assignments.")

        register = registers[0]
        session = (
            RegisterSession.all_objects.select_related("register", "business_day")
            # Explicit, not the bare related name. `operator_shifts` resolves
            # through OperatorShift's tenant-strict manager, which returns
            # nothing when no tenant id is on the thread -- and this feeds the
            # readiness a till checks before it will sell. An empty result reads
            # as "no accountable operator shift", so the till would be told it
            # is not ready for a reason that has nothing to do with the till.
            .prefetch_related(
                Prefetch(
                    "operator_shifts",
                    queryset=OperatorShift.all_objects.filter(
                        tenant=tenant
                    ).select_related("operator", "handed_over_to"),
                )
            )
            .filter(tenant=tenant, register=register, state="OPEN")
            .order_by("-opened_at")
            .first()
        )
        business_day = session.business_day if session else (
            BusinessDay.all_objects.filter(tenant=tenant, location=register.location, state__in=["OPEN", "REOPENED_BY_EXCEPTION"])
            .order_by("-business_date")
            .first()
        )
        operator_shift = None
        if session and actor:
            operator_shift = (
                OperatorShift.all_objects.filter(
                    tenant=tenant,
                    register_session=session,
                    operator=actor,
                    state__in=["OPEN", "HANDOVER_REQUESTED"],
                )
                .order_by("-started_at")
                .first()
            )
        device_health = PosDeviceHealthRecord.all_objects.filter(
            tenant=tenant, device_id=device_id
        ).first()

        notices: list[str] = []
        if register.state != "OPEN":
            notices.append(f"Register {register.code} is {register.state}.")
        if session is None:
            notices.append(f"Register {register.code} has no open register session.")
        elif not register_accepts_transactions(session):
            notices.append("The current register session does not accept transactions.")
        if business_day is None or not business_day.accepts_transactions:
            notices.append("The current business day does not accept transactions.")
        if operator_shift is None:
            notices.append("No active accountable operator shift was found for this session.")
        if device_health is None:
            notices.append("No current device and printer health report is available.")
        elif device_health.status in {"ERROR", "OFFLINE"}:
            notices.append("The device health service reports this terminal as unavailable.")
        elif device_health.status == "WARNING" or device_health.printer_paper_level != "OK":
            notices.append("The device or printer requires attention before continuing.")

        readiness = "READY" if not notices else "ATTENTION"
        allowed_actions: list[str] = []
        actor_has_shift = operator_shift is not None
        pending_handover = (
            OperatorShift.all_objects.filter(
                tenant=tenant,
                register_session=session,
                state="HANDOVER_REQUESTED",
            )
            .exclude(operator_id=getattr(actor, "pk", None))
            .order_by("-started_at")
            .first()
            if session
            else None
        )
        if (
            session is None
            and register.accepts_opening
            and business_day is not None
            and business_day.accepts_transactions
            and actor
            and (
                actor.has_capability("pos.register.open", tenant_id=tenant.pk)
                or actor.has_capability("pos.shift.manage", tenant_id=tenant.pk)
            )
        ):
            allowed_actions.append("OPEN_REGISTER")
        if readiness == "READY" and actor_has_shift and actor and actor.has_capability("pos.transaction.create", tenant_id=tenant.pk):
            allowed_actions.append("START_SALE")
        if actor_has_shift and actor and (
            actor.has_capability("pos.shift.handover", tenant_id=tenant.pk)
            or actor.has_capability("pos.shift.manage", tenant_id=tenant.pk)
        ):
            allowed_actions.append(
                "CANCEL_HANDOVER"
                if operator_shift and operator_shift.state == "HANDOVER_REQUESTED"
                else "REQUEST_HANDOVER"
            )
        if pending_handover and actor and (
            actor.has_capability("pos.shift.handover", tenant_id=tenant.pk)
            or actor.has_capability("pos.shift.manage", tenant_id=tenant.pk)
        ):
            allowed_actions.append("ACCEPT_HANDOVER")
        if actor_has_shift and actor and (
            actor.has_capability("pos.cash.movement.create", tenant_id=tenant.pk)
            or actor.has_capability("pos.shift.manage", tenant_id=tenant.pk)
        ):
            allowed_actions.append("RECORD_CASH_MOVEMENT")
        if session and actor and actor.has_capability("pos.cash.movement.approve", tenant_id=tenant.pk):
            allowed_actions.append("APPROVE_CASH_MOVEMENT")
        if actor_has_shift and actor and actor.has_capability("pos.report.x.generate", tenant_id=tenant.pk):
            allowed_actions.append("GENERATE_X_REPORT")
        if actor_has_shift and actor and actor.has_capability("pos.report.z.generate", tenant_id=tenant.pk):
            allowed_actions.append("CLOSE_REGISTER")

        return {
            "readiness": readiness,
            "register": register,
            "business_day": business_day,
            "register_session": session,
            "operator_shift": operator_shift,
            "device_health": device_health,
            "notices": notices,
            "allowed_actions": allowed_actions,
            "closure_eligibility": cls._closure_eligibility(session),
        }

    @staticmethod
    def _unassigned(message: str) -> dict:
        return {
            "readiness": "UNASSIGNED",
            "register": None,
            "business_day": None,
            "register_session": None,
            "operator_shift": None,
            "device_health": None,
            "notices": [message],
            "allowed_actions": [],
            "closure_eligibility": {"eligible": False, "blocking_reasons": [message]},
        }

    @staticmethod
    def _closure_eligibility(session: RegisterSession | None) -> dict:
        if session is None:
            return {"eligible": False, "blocking_reasons": ["No open register session."]}
        problems = ShiftReportService.check_closure_preconditions(session=session)
        return {
            "eligible": not problems,
            "blocking_reasons": [problem["message"] for problem in problems],
        }
