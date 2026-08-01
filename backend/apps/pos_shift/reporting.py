"""X and Z report generation.

The two are not variants of one report. An X answers "where are we now"; a Z
answers "this session is closed and these are its final figures". Conflating
them is how a register gets reset by someone who only wanted to look at it.

Three properties are enforced here rather than left to callers:

**An X never closes anything.** It writes a report row and touches nothing else
-- no session state, no counters, no settlement, no finance posting. Its period
start is always the session opening, so an X is cumulative rather than a delta
since the last one.

**A Z happens exactly once per session.** The partial unique index on
ShiftReport is the real guard; this service adds a locking read so the losing
request of a concurrent pair gets a clear error rather than an integrity error.

**Printing is outside the closure transaction.** A Z that finalised but failed
to print is closed and reprintable. Rolling the closure back because a printer
jammed would reopen a register whose drawer has already been counted and
removed.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.money import format_money

from .cash_control import CashControlService, money
from .models import (
    ZERO,
    BusinessDay,
    CashDeclaration,
    CashMovement,
    OperatorShift,
    RegisterSession,
    ShiftReport,
    ShiftReportReprint,
)


class RegisterAlreadyClosed(ValidationError):
    """The session already has a final Z."""


class ClosurePreconditionFailed(ValidationError):
    """Something unresolved blocks closure."""


def build_report_number(*, session: RegisterSession, report_type: str, sequence: int) -> str:
    """Branch/Register/BusinessDate/Type/Sequence.

    Readable on a printed slip and sortable in a spreadsheet, which is how these
    are actually reconciled.
    """
    branch = getattr(session.register.location, "code", None) or str(session.register.location_id)[:8]
    return (
        f"{branch}/{session.register.code}/"
        f"{session.business_day.business_date.isoformat()}/{report_type}/"
        f"{sequence:04d}"
    )


def _next_sequence(*, session: RegisterSession, report_type: str) -> int:
    """Next sequence for this register, business date and report type."""
    highest = (
        ShiftReport.all_objects.filter(
            tenant_id=session.tenant_id,
            register_session__register_id=session.register_id,
            business_day_id=session.business_day_id,
            report_type=report_type,
        ).aggregate(Max("sequence"))["sequence__max"]
        or 0
    )
    return highest + 1


class ShiftReportService:
    """Produces X and Z reports from authoritative ledger rows."""

    # ------------------------------------------------------------- snapshot

    @staticmethod
    def build_snapshot(*, session: RegisterSession, declared_cash: Decimal | None = None,
                       cash_refunds: Decimal | None = None, tolerance: Decimal | None = None) -> dict:
        """Compute the figures for a report.

        Returned as plain JSON-safe types because this is persisted verbatim and
        read back by HQ without recalculation. Decimals are serialised as
        strings, never floats: a Z report stored as a float is a Z report whose
        totals can disagree with themselves.
        """
        breakdown = CashControlService.tender_breakdown(session=session)
        expected = CashControlService.expected_cash(session=session, cash_refunds=cash_refunds)

        variance = None
        if declared_cash is not None:
            variance_result = CashControlService.variance(
                declared=declared_cash,
                expected=expected.expected,
                tolerance=tolerance if tolerance is not None else ZERO,
            )
            variance = {
                "declared": format_money(variance_result.declared),
                "expected": format_money(variance_result.expected),
                "difference": format_money(variance_result.difference),
                "classification": variance_result.classification,
                "requires_explanation": variance_result.requires_explanation,
            }

        movements = [
            {
                "kind": movement.kind,
                "amount": format_money(money(movement.amount)),
                "affects_expected_cash": movement.affects_expected_cash,
                "reference": movement.reference,
            }
            for movement in CashMovement.all_objects.filter(
                tenant_id=session.tenant_id, register_session=session
            )
        ]

        return {
            "period_start": session.opened_at.isoformat(),
            "generated_at": timezone.now().isoformat(),
            "currency": session.register.currency,
            "cash": {
                "opening": format_money(expected.opening),
                "cash_sales": format_money(expected.cash_sales),
                "cash_in": format_money(expected.cash_in),
                "cash_out": format_money(expected.cash_out),
                "cash_refunds": format_money(expected.cash_refunds),
                "expected_closing": format_money(expected.expected),
            },
            "tenders": {
                # Cash and non-cash are reported side by side but never summed
                # into a single "takings" figure that a drawer gets counted
                # against.
                "by_type": {k: format_money(v) for k, v in sorted(breakdown.by_type.items())},
                "cash_total": format_money(breakdown.cash),
                "non_cash_total": format_money(breakdown.non_cash),
                "grand_total": format_money(breakdown.total),
            },
            "cash_movements": movements,
            "variance": variance,
        }

    # -------------------------------------------------------------- X report

    @classmethod
    def generate_x(cls, *, session: RegisterSession, actor, cash_refunds: Decimal | None = None) -> ShiftReport:
        """An interim snapshot. Changes nothing.

        Permitted on an open or closing session. Refused once a Z exists,
        because "where are we now" has no meaning after the session is final --
        and an X printed after closure would look like evidence of activity
        after the Z.
        """
        if cls.final_report(session=session) is not None:
            raise RegisterAlreadyClosed(
                "This register session is closed. Reprint the Z report instead."
            )

        sequence = _next_sequence(session=session, report_type=ShiftReport.TYPE_X)
        return ShiftReport.all_objects.create(
            tenant_id=session.tenant_id,
            register_session=session,
            operator_shift=cls.active_shift(session=session),
            business_day=session.business_day,
            report_type=ShiftReport.TYPE_X,
            report_number=build_report_number(
                session=session, report_type=ShiftReport.TYPE_X, sequence=sequence
            ),
            sequence=sequence,
            # Always the session opening. An X is cumulative, never a delta
            # since the previous X.
            period_start=session.opened_at,
            generated_by=actor,
            snapshot=cls.build_snapshot(session=session, cash_refunds=cash_refunds),
        )

    # -------------------------------------------------------------- Z report

    @staticmethod
    def final_report(*, session: RegisterSession) -> ShiftReport | None:
        return ShiftReport.all_objects.filter(
            tenant_id=session.tenant_id, register_session=session, report_type=ShiftReport.TYPE_Z
        ).first()

    @staticmethod
    def active_shift(*, session: RegisterSession) -> OperatorShift | None:
        return OperatorShift.all_objects.filter(
            tenant_id=session.tenant_id,
            register_session=session,
            state__in=["OPEN", "HANDOVER_REQUESTED"],
        ).first()

    @classmethod
    def check_closure_preconditions(cls, *, session: RegisterSession, allow_exceptions: bool = False) -> list[dict]:
        """Return the unresolved items blocking closure.

        Returns them all rather than the first, so an operator is told
        everything they must resolve instead of discovering it one refusal at a
        time.
        """
        problems: list[dict] = []

        closing = (
            CashDeclaration.all_objects.filter(
                tenant_id=session.tenant_id,
                register_session=session,
                kind="CLOSING",
                confirmed_at__isnull=False,
            )
            .order_by("-attempt")
            .first()
        )
        if closing is None:
            problems.append(
                {
                    "code": "CLOSING_DECLARATION_MISSING",
                    "message": "A confirmed closing cash declaration is required.",
                    "waivable": False,
                }
            )

        unapproved = CashMovement.all_objects.filter(
            tenant_id=session.tenant_id, register_session=session, approved_at__isnull=True
        ).count()
        if unapproved:
            problems.append(
                {
                    "code": "CASH_MOVEMENTS_UNAPPROVED",
                    "message": f"{unapproved} cash movement(s) await approval.",
                    "waivable": True,
                }
            )

        if allow_exceptions:
            # Waivable items become exceptions printed on the report rather than
            # silent omissions. A blocker is never waivable.
            problems = [p for p in problems if not p["waivable"]]
        return problems

    @classmethod
    @transaction.atomic
    def finalise_z(
        cls,
        *,
        session: RegisterSession,
        actor,
        declared_cash: Decimal,
        cash_refunds: Decimal | None = None,
        tolerance: Decimal | None = None,
        forced: bool = False,
        reason: str = "",
        approver=None,
        allow_exceptions: bool = False,
    ) -> ShiftReport:
        """Close the session and freeze its figures, in one transaction.

        Deliberately does not print. Printing is enqueued by the caller after
        this commits, so a printer failure leaves a closed session with a
        reprintable report rather than rolling back a closure whose drawer has
        already been counted and removed.
        """
        # Lock the session row so a concurrent closure serialises behind this
        # one and then sees the Z that this one wrote.
        locked = RegisterSession.all_objects.select_for_update().get(
            pk=session.pk, tenant_id=session.tenant_id
        )

        existing = cls.final_report(session=locked)
        if existing is not None:
            raise RegisterAlreadyClosed(
                f"This register session was already closed by {existing.report_number}."
            )

        if forced and not approver:
            # A forced closure is somebody overriding the person accountable for
            # the drawer. It is not anonymous.
            raise PermissionDenied("A forced closure requires a named approver.")
        if forced and not reason.strip():
            raise ValidationError("A forced closure requires a reason.")

        problems = cls.check_closure_preconditions(
            session=locked, allow_exceptions=allow_exceptions or forced
        )
        if problems:
            raise ClosurePreconditionFailed(
                {"closure": [p["message"] for p in problems]}
            )

        waived = [
            p
            for p in cls.check_closure_preconditions(session=locked, allow_exceptions=False)
            if p["waivable"]
        ]

        sequence = _next_sequence(session=locked, report_type=ShiftReport.TYPE_Z)
        report = ShiftReport.all_objects.create(
            tenant_id=locked.tenant_id,
            register_session=locked,
            operator_shift=cls.active_shift(session=locked),
            business_day=locked.business_day,
            report_type=ShiftReport.TYPE_Z,
            report_number=build_report_number(
                session=locked, report_type=ShiftReport.TYPE_Z, sequence=sequence
            ),
            sequence=sequence,
            period_start=locked.opened_at,
            generated_by=actor,
            closure_type=ShiftReport.CLOSURE_FORCED if forced else ShiftReport.CLOSURE_NORMAL,
            closure_reason=reason,
            approved_by=approver,
            snapshot=cls.build_snapshot(
                session=locked,
                declared_cash=declared_cash,
                cash_refunds=cash_refunds,
                tolerance=tolerance,
            ),
            exceptions=waived,
        )

        now = timezone.now()
        locked.state = "CLOSED"
        locked.closed_at = now
        locked.closed_by = actor
        locked.forced_closure = forced
        locked.forced_closure_reason = reason
        locked.save(
            update_fields=[
                "state", "closed_at", "closed_by", "forced_closure",
                "forced_closure_reason", "updated_at",
            ]
        )

        OperatorShift.all_objects.filter(
            tenant_id=locked.tenant_id, register_session=locked, state__in=["OPEN", "HANDOVER_REQUESTED"]
        ).update(
            state="FORCE_CLOSED" if forced else "CLOSED",
            ended_at=now,
            closed_by=actor,
            updated_at=now,
        )

        register = locked.register
        register.state = "CLOSED"
        register.save(update_fields=["state", "updated_at"])

        return report

    # -------------------------------------------------------------- reprint

    @staticmethod
    def reprint(*, report: ShiftReport, actor, reason: str, printer: str = "") -> ShiftReportReprint:
        """Record a reprint. The original report number is retained.

        Issuing a new number would let a reprint be presented as a separate
        closure, which is how one day's takings get banked twice.
        """
        if not reason.strip():
            raise ValidationError("A reprint requires a reason.")

        copy_number = (
            ShiftReportReprint.all_objects.filter(
                tenant_id=report.tenant_id, report=report
            ).aggregate(Max("copy_number"))["copy_number__max"]
            or 1
        ) + 1

        return ShiftReportReprint.all_objects.create(
            tenant_id=report.tenant_id,
            report=report,
            copy_number=copy_number,
            reason=reason,
            reprinted_by=actor,
            printer=printer,
        )


def register_accepts_transactions(session: RegisterSession) -> bool:
    """Whether new transactions may be posted to this session.

    False once a Z exists, whatever the session row says. The report is the
    authority on closure: a session row edited back to OPEN must not reopen
    trading against a set of figures that have already been signed off.
    """
    if session.state != "OPEN":
        return False
    if not isinstance(session.business_day, BusinessDay):
        return False
    if not session.business_day.accepts_transactions:
        return False
    return ShiftReportService.final_report(session=session) is None
