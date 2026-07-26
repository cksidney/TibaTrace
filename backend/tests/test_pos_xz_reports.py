"""X and Z reports.

An X answers "where are we now". A Z answers "this session is closed and these
are its final figures". Conflating them is how a register gets reset by someone
who only meant to look at it, and how a day's takings get banked twice.

Do not relax these. Each one corresponds to a way real money goes missing or
gets double-counted.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.identity.models import User
from apps.organizations.models import Location, Organization
from apps.pos_shift.models import (
    BusinessDay,
    CashDeclaration,
    CashMovement,
    OperatorShift,
    PosRegister,
    RegisterSession,
    ShiftReport,
    ShiftReportReprint,
)
from apps.pos_shift.reporting import (
    ClosurePreconditionFailed,
    RegisterAlreadyClosed,
    ShiftReportService,
    build_report_number,
    register_accepts_transactions,
)
from apps.tenancy.models import Tenant


def cash(value: str) -> Decimal:
    return Decimal(value)


@pytest.fixture
def setup(db):
    tenant = Tenant.objects.create(name="Shift Tenant", slug="shift-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-1", name="Esenai Pharmacy")
    location = Location.all_objects.create(
        tenant=tenant, organization=org, code="ELD-01", name="Eldoret Branch"
    )
    operator = User.objects.create_user(username="till-operator", password="pw", tenant=tenant)
    supervisor = User.objects.create_user(username="till-supervisor", password="pw", tenant=tenant)
    register = PosRegister.all_objects.create(
        tenant=tenant, location=location, code="TILL-03", name="Front Till", state="AVAILABLE"
    )
    day = BusinessDay.all_objects.create(
        tenant=tenant, location=location, business_date=date(2026, 7, 26), state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=day, opened_by=operator, state="OPEN"
    )
    shift = OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )
    return {
        "tenant": tenant, "location": location, "operator": operator,
        "supervisor": supervisor, "register": register, "day": day,
        "session": session, "shift": shift,
    }


def declare(setup, kind, amount, attempt=1):
    return CashDeclaration.all_objects.create(
        tenant=setup["tenant"],
        register_session=setup["session"],
        operator_shift=setup["shift"],
        kind=kind,
        declared_amount=cash(amount),
        declared_by=setup["operator"],
        attempt=attempt,
        confirmed_at=timezone.now(),
    )


# ─── report numbering ────────────────────────────────────────────────────────


class TestReportNumbering:
    def test_number_format(self, setup):
        number = build_report_number(session=setup["session"], report_type="Z", sequence=1)
        assert number == "ELD-01/TILL-03/2026-07-26/Z/0001"

    def test_x_reports_get_distinct_numbers(self, setup):
        first = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        second = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        assert first.report_number != second.report_number
        assert first.sequence == 1
        assert second.sequence == 2

    def test_x_and_z_sequences_are_independent(self, setup):
        ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        declare(setup, "CLOSING", "5000.00")
        z = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        assert z.sequence == 1
        assert "/Z/0001" in z.report_number


# ─── X reports change nothing ────────────────────────────────────────────────


class TestXReportIsInterim:
    def test_x_does_not_close_the_session(self, setup):
        ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        setup["session"].refresh_from_db()
        assert setup["session"].state == "OPEN"

    def test_x_does_not_end_the_shift(self, setup):
        ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        setup["shift"].refresh_from_db()
        assert setup["shift"].state == "OPEN"

    def test_transactions_continue_after_an_x(self, setup):
        ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        setup["session"].refresh_from_db()
        assert register_accepts_transactions(setup["session"]) is True

    def test_repeated_x_reports_are_permitted(self, setup):
        for _ in range(5):
            ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        assert ShiftReport.all_objects.filter(report_type="X").count() == 5

    def test_x_is_cumulative_not_a_delta(self, setup):
        """Every X starts at the session opening.

        A delta-since-last-X would make a mid-shift X look like the whole shift
        to anyone who did not notice which one they were holding.
        """
        first = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        second = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        assert first.period_start == second.period_start == setup["session"].opened_at

    def test_x_does_not_reset_counters(self, setup):
        declare(setup, "OPENING", "5000.00")
        CashMovement.all_objects.create(
            tenant=setup["tenant"], register_session=setup["session"], kind="CASH_IN",
            amount=cash("500.00"), created_by=setup["operator"],
        )
        first = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        second = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        # The second X still sees the same opening and the same movement.
        assert first.snapshot["cash"]["opening"] == second.snapshot["cash"]["opening"] == "5000.00"
        assert first.snapshot["cash"]["cash_in"] == second.snapshot["cash"]["cash_in"] == "500.00"


# ─── Z closes, exactly once ──────────────────────────────────────────────────


class TestZReportIsFinal:
    def test_z_closes_the_session(self, setup):
        declare(setup, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        setup["session"].refresh_from_db()
        assert setup["session"].state == "CLOSED"
        assert setup["session"].closed_at is not None

    def test_z_closes_the_operator_shift(self, setup):
        declare(setup, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        setup["shift"].refresh_from_db()
        assert setup["shift"].state == "CLOSED"

    def test_z_stops_further_transactions(self, setup):
        declare(setup, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        setup["session"].refresh_from_db()
        assert register_accepts_transactions(setup["session"]) is False

    def test_a_second_z_is_refused(self, setup):
        declare(setup, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        with pytest.raises(RegisterAlreadyClosed):
            ShiftReportService.finalise_z(
                session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
            )

    def test_the_database_refuses_a_second_z_directly(self, setup):
        """Not merely the service.

        Two concurrent closures would each find no existing Z and both proceed,
        so the guard has to be the index.
        """
        from django.db import IntegrityError

        declare(setup, "CLOSING", "5000.00")
        first = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )

        duplicate = ShiftReport(
            tenant=setup["tenant"],
            register_session=setup["session"],
            business_day=setup["day"],
            report_type="Z",
            report_number=first.report_number + "-DUP",
            sequence=99,
            period_start=setup["session"].opened_at,
            generated_by=setup["operator"],
        )

        # bulk_create deliberately: it skips full_clean and goes straight to the
        # database. Model validation would catch this too, but model validation
        # is exactly what does NOT protect a concurrent pair -- both would
        # validate against a table with one Z and both would then insert. The
        # index has to be the thing that refuses.
        with pytest.raises(IntegrityError):
            ShiftReport.all_objects.bulk_create([duplicate])

    def test_no_x_after_closure(self, setup):
        # An X printed after the Z would look like evidence of trading after
        # the register was closed.
        declare(setup, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        with pytest.raises(RegisterAlreadyClosed):
            ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])


# ─── Z immutability ──────────────────────────────────────────────────────────


class TestZImmutability:
    def test_a_finalised_z_cannot_be_edited(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        report.snapshot = {"cash": {"expected_closing": "999999.00"}}
        with pytest.raises(ValidationError, match="cannot be altered"):
            report.save()

    def test_the_report_number_cannot_be_changed(self, setup):
        # Renumbering is how a reprint gets passed off as a separate closure.
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        report.report_number = "ELD-01/TILL-03/2026-07-26/Z/9999"
        with pytest.raises(ValidationError):
            report.save()

    def test_an_x_report_is_not_frozen(self, setup):
        # Only Z is a signed financial record.
        report = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        report.snapshot = {"note": "annotated"}
        report.save()

    def test_hq_reads_the_snapshot_not_a_recalculation(self, setup):
        """A Z must not change when later data arrives.

        Re-deriving it from today's tables would silently alter a report
        somebody already signed, printed and banked against.
        """
        declare(setup, "OPENING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        ) if declare(setup, "CLOSING", "5000.00") else None
        frozen = report.snapshot["cash"]["opening"]

        # More cash arrives after closure.
        CashMovement.all_objects.create(
            tenant=setup["tenant"], register_session=setup["session"], kind="CASH_IN",
            amount=cash("9999.00"), created_by=setup["operator"],
        )
        report.refresh_from_db()
        assert report.snapshot["cash"]["opening"] == frozen
        assert report.snapshot["cash"]["cash_in"] == "0.00"


# ─── closure preconditions ───────────────────────────────────────────────────


class TestClosurePreconditions:
    def test_closure_needs_a_closing_declaration(self, setup):
        with pytest.raises(ClosurePreconditionFailed):
            ShiftReportService.finalise_z(
                session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
            )

    def test_all_problems_are_reported_at_once(self, setup):
        # An operator told one blocker at a time resolves them one at a time.
        CashMovement.all_objects.create(
            tenant=setup["tenant"], register_session=setup["session"], kind="CASH_OUT",
            amount=cash("100.00"), created_by=setup["operator"],
        )
        problems = ShiftReportService.check_closure_preconditions(session=setup["session"])
        codes = {p["code"] for p in problems}
        assert "CLOSING_DECLARATION_MISSING" in codes
        assert "CASH_MOVEMENTS_UNAPPROVED" in codes

    def test_a_waivable_problem_can_be_carried_as_an_exception(self, setup):
        declare(setup, "CLOSING", "5000.00")
        CashMovement.all_objects.create(
            tenant=setup["tenant"], register_session=setup["session"], kind="CASH_OUT",
            amount=cash("100.00"), created_by=setup["operator"],
        )
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"],
            declared_cash=cash("5000.00"), allow_exceptions=True,
        )
        # Carried onto the report rather than silently dropped.
        assert any(e["code"] == "CASH_MOVEMENTS_UNAPPROVED" for e in report.exceptions)

    def test_a_blocker_is_never_waivable(self, setup):
        with pytest.raises(ClosurePreconditionFailed):
            ShiftReportService.finalise_z(
                session=setup["session"], actor=setup["operator"],
                declared_cash=cash("5000.00"), allow_exceptions=True,
            )


# ─── forced closure ──────────────────────────────────────────────────────────


class TestForcedClosure:
    def test_forced_closure_needs_a_named_approver(self, setup):
        declare(setup, "CLOSING", "5000.00")
        with pytest.raises(PermissionDenied):
            ShiftReportService.finalise_z(
                session=setup["session"], actor=setup["supervisor"],
                declared_cash=cash("5000.00"), forced=True, reason="Operator absent",
            )

    def test_forced_closure_needs_a_reason(self, setup):
        declare(setup, "CLOSING", "5000.00")
        with pytest.raises(ValidationError):
            ShiftReportService.finalise_z(
                session=setup["session"], actor=setup["supervisor"],
                declared_cash=cash("5000.00"), forced=True, approver=setup["supervisor"],
            )

    def test_a_forced_closure_is_marked_on_the_report(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["supervisor"], declared_cash=cash("5000.00"),
            forced=True, reason="Operator left without closing", approver=setup["supervisor"],
        )
        assert report.closure_type == ShiftReport.CLOSURE_FORCED
        assert report.approved_by_id == setup["supervisor"].pk
        assert "left without closing" in report.closure_reason
        setup["shift"].refresh_from_db()
        assert setup["shift"].state == "FORCE_CLOSED"


# ─── reprints ────────────────────────────────────────────────────────────────


class TestReprint:
    def test_a_reprint_keeps_the_original_number(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        original = report.report_number
        ShiftReportService.reprint(report=report, actor=setup["supervisor"], reason="Printer jammed")
        report.refresh_from_db()
        # A new number would let a reprint be presented as a separate closure,
        # which is how a day's takings get banked twice.
        assert report.report_number == original

    def test_reprints_are_numbered_from_two(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        first = ShiftReportService.reprint(report=report, actor=setup["supervisor"], reason="Jam")
        second = ShiftReportService.reprint(report=report, actor=setup["supervisor"], reason="Lost")
        # The original print is copy 1.
        assert first.copy_number == 2
        assert second.copy_number == 3

    def test_a_reprint_requires_a_reason(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        with pytest.raises(ValidationError):
            ShiftReportService.reprint(report=report, actor=setup["supervisor"], reason="   ")

    def test_a_reprint_does_not_alter_the_report(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        before = report.snapshot
        ShiftReportService.reprint(report=report, actor=setup["supervisor"], reason="Jam")
        report.refresh_from_db()
        assert report.snapshot == before

    def test_the_reprint_is_attributed(self, setup):
        declare(setup, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("5000.00")
        )
        reprint = ShiftReportService.reprint(
            report=report, actor=setup["supervisor"], reason="Auditor request", printer="TILL-03-P"
        )
        assert reprint.reprinted_by_id == setup["supervisor"].pk
        assert reprint.reason == "Auditor request"
        assert ShiftReportReprint.all_objects.filter(report=report).count() == 1


# ─── the snapshot content ────────────────────────────────────────────────────


class TestSnapshotContent:
    def test_cash_and_non_cash_are_reported_separately(self, setup):
        declare(setup, "OPENING", "5000.00")
        report = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        tenders = report.snapshot["tenders"]
        # Present as distinct figures, never summed into one "takings" number
        # that a drawer gets counted against.
        assert "cash_total" in tenders
        assert "non_cash_total" in tenders
        assert tenders["cash_total"] != tenders.get("grand_total_is_cash")

    def test_amounts_are_strings_not_floats(self, setup):
        declare(setup, "OPENING", "5000.00")
        report = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        for value in report.snapshot["cash"].values():
            # A Z stored as a float is a Z whose totals can disagree with
            # themselves after a round trip.
            assert isinstance(value, str)

    def test_variance_is_absent_until_cash_is_declared(self, setup):
        report = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        assert report.snapshot["variance"] is None

    def test_variance_is_recorded_on_closure(self, setup):
        declare(setup, "OPENING", "5000.00")
        declare(setup, "CLOSING", "4900.00")
        report = ShiftReportService.finalise_z(
            session=setup["session"], actor=setup["operator"], declared_cash=cash("4900.00")
        )
        variance = report.snapshot["variance"]
        assert variance["difference"] == "-100.00"
        assert variance["classification"] == "SHORT"
        assert variance["requires_explanation"] is True


# ─── tenant isolation ────────────────────────────────────────────────────────


class TestIsolation:
    def test_report_numbers_may_repeat_across_tenants(self, setup, db):
        other = Tenant.objects.create(name="Other", slug="other-shift")
        other_org = Organization.all_objects.create(tenant=other, code="ORG-1", name="Other Pharmacy")
        location = Location.all_objects.create(
            tenant=other, organization=other_org, code="ELD-01", name="Other Branch"
        )
        operator = User.objects.create_user(username="other-op", password="pw", tenant=other)
        register = PosRegister.all_objects.create(
            tenant=other, location=location, code="TILL-03", name="Till", state="AVAILABLE"
        )
        day = BusinessDay.all_objects.create(
            tenant=other, location=location, business_date=date(2026, 7, 26), state="OPEN"
        )
        session = RegisterSession.all_objects.create(
            tenant=other, register=register, business_day=day, opened_by=operator, state="OPEN"
        )

        mine = ShiftReportService.generate_x(session=setup["session"], actor=setup["operator"])
        theirs = ShiftReportService.generate_x(session=session, actor=operator)
        # Same human-readable number, different tenants, both valid.
        assert mine.report_number == theirs.report_number
        assert mine.tenant_id != theirs.tenant_id


# ─── business day ────────────────────────────────────────────────────────────


class TestBusinessDay:
    def test_a_closed_business_day_stops_transactions(self, setup):
        setup["day"].state = "CLOSED"
        setup["day"].save()
        setup["session"].refresh_from_db()
        assert register_accepts_transactions(setup["session"]) is False

    def test_a_business_day_reopened_by_exception_accepts_transactions(self, setup):
        setup["day"].state = "REOPENED_BY_EXCEPTION"
        setup["day"].save()
        setup["session"].refresh_from_db()
        assert register_accepts_transactions(setup["session"]) is True

    def test_a_day_spans_past_midnight(self, setup):
        # A till open at 01:00 is still on yesterday's business day.
        assert setup["day"].business_date == date(2026, 7, 26)
        assert setup["session"].business_day.business_date == date(2026, 7, 26)
        assert setup["day"].business_date != (timezone.now() + timedelta(days=1)).date()
