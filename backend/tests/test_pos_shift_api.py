"""The shift, cash-control and X/Z workbench API.

Two properties. Nothing here can close a till, because closure runs through a
service that enforces one-Z-per-session and a named approver on a forced
closure. And a Z report is served from its frozen snapshot, never recomputed --
it is what somebody counted, signed and banked against, and the operator holds
the printed copy.
"""
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.organizations.models import Location, Organization
from apps.pos_shift.models import (
    BusinessDay,
    CashDeclaration,
    CashMovement,
    OperatorShift,
    PosRegister,
    RegisterSession,
)
from apps.pos_shift.reporting import ShiftReportService
from apps.prescription.models import PosDeviceHealthRecord
from apps.tenancy.models import Tenant

TODAY = date(2026, 7, 26)


def cash(value: str) -> Decimal:
    return Decimal(value)


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Shift API Tenant", slug="shift-api")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-SA", name="Group")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="ELD-SA", name="Eldoret")
    operator = User.objects.create_user(username="till-op", password="pw", tenant=tenant)
    supervisor = User.objects.create_user(username="till-sup", password="pw", tenant=tenant)
    register = PosRegister.all_objects.create(
        tenant=tenant, location=branch, code="TILL-SA", name="Front", state="AVAILABLE"
    )
    day = BusinessDay.all_objects.create(
        tenant=tenant, location=branch, business_date=TODAY, state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=day, opened_by=operator, state="OPEN"
    )
    OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )
    api = APIClient()
    api.force_authenticate(user=operator)
    return {
        "tenant": tenant, "branch": branch, "operator": operator,
        "supervisor": supervisor, "register": register, "day": day,
        "session": session, "client": api,
    }


def declare(world, kind, amount):
    from django.utils import timezone

    return CashDeclaration.all_objects.create(
        tenant=world["tenant"], register_session=world["session"], kind=kind,
        declared_amount=cash(amount), declared_by=world["operator"],
        confirmed_at=timezone.now(),
    )


# ─── nothing here closes a till ──────────────────────────────────────────────


class TestReadOnly:
    @pytest.mark.parametrize(
        "collection",
        ["registers", "business-days", "sessions", "shifts",
         "cash-declarations", "cash-movements", "reports", "reprints"],
    )
    def test_collections_refuse_creation(self, world, collection):
        response = world["client"].post(f"/api/pos/shift/{collection}/", {}, format="json")
        assert response.status_code in (403, 405)

    def test_a_session_cannot_be_closed_through_the_api(self, world):
        """Closure enforces one Z per session and a named approver on a forced
        closure. A PATCH would skip both."""
        response = world["client"].patch(
            f"/api/pos/shift/sessions/{world['session'].pk}/",
            {"state": "CLOSED"}, format="json",
        )
        assert response.status_code in (403, 405)

    def test_a_report_snapshot_cannot_be_edited(self, world):
        # A Z is what somebody signed. Corrections go through adjustment.
        declare(world, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )
        response = world["client"].patch(
            f"/api/pos/shift/reports/{report.pk}/",
            {"snapshot": {"cash": {"expected_closing": "0.00"}}}, format="json",
        )
        assert response.status_code in (403, 405)


# ─── reports come from their snapshot ────────────────────────────────────────


class TestSnapshotFidelity:
    def test_a_z_report_serves_its_frozen_figures(self, world):
        declare(world, "OPENING", "5000.00")
        declare(world, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )

        body = rows(world["client"].get("/api/pos/shift/reports/"))
        served = next(r for r in body if r["report_number"] == report.report_number)
        assert served["snapshot"]["cash"]["opening"] == "5000.00"

    def test_the_snapshot_does_not_move_when_later_cash_arrives(self, world):
        """HQ never recalculates a Z.

        Re-deriving it from current data would restate history while the
        operator holds the printed copy.
        """
        declare(world, "OPENING", "5000.00")
        declare(world, "CLOSING", "5000.00")
        report = ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )

        CashMovement.all_objects.create(
            tenant=world["tenant"], register_session=world["session"], kind="CASH_IN",
            amount=cash("9999.00"), created_by=world["operator"],
        )

        body = rows(world["client"].get("/api/pos/shift/reports/"))
        served = next(r for r in body if r["report_number"] == report.report_number)
        assert served["snapshot"]["cash"]["cash_in"] == "0.00"

    def test_money_is_serialised_as_a_string(self, world):
        """JSON numbers are binary floats.

        A till total that round-trips through one stops matching the drawer.
        """
        body = rows(world["client"].get("/api/pos/shift/registers/"))
        assert isinstance(body[0]["expected_float"], str)


# ─── the lists somebody checks ───────────────────────────────────────────────


class TestWorkbenchLists:
    def test_open_sessions_are_listed(self, world):
        """The list checked at close of business to find a till nobody closed.

        Otherwise it is found the next morning, after a night of unreconciled
        cash.
        """
        body = rows(world["client"].get("/api/pos/shift/sessions/open/"))
        assert len(body) == 1
        assert body[0]["state"] == "OPEN"

    def test_runtime_returns_one_authoritative_operational_context(self, world):
        register = world["register"]
        register.state = "OPEN"
        register.device_id = "POS-SA-01"
        register.save(update_fields=["state", "device_id", "updated_at"])
        PosDeviceHealthRecord.all_objects.create(
            tenant=world["tenant"],
            device_id="POS-SA-01",
            device_type="TERMINAL",
            status="OK",
            printer_paper_level="OK",
        )

        response = world["client"].get("/api/pos/shift/registers/runtime/?device_id=POS-SA-01")

        assert response.status_code == 200
        body = response.json()
        assert body["readiness"] == "READY"
        assert body["register"]["code"] == "TILL-SA"
        assert body["register_session"]["id"] == str(world["session"].pk)
        assert body["operator_shift"]["operator_id"] == str(world["operator"].pk)
        assert body["business_day"]["business_date"] == TODAY.isoformat()

    def test_runtime_does_not_guess_an_unassigned_register(self, world):
        response = world["client"].get("/api/pos/shift/registers/runtime/?device_id=UNKNOWN")

        assert response.status_code == 200
        body = response.json()
        assert body["readiness"] == "UNASSIGNED"
        assert body["allowed_actions"] == []
        assert body["notices"] == ["This device is not assigned to a register."]

    def test_open_session_exposes_stable_operator_identity(self, world):
        """Native tills match the accountable shift to the authenticated user.

        This must use the immutable user id, not a username that an
        administrator can rename while the register session is still open.
        """
        body = rows(world["client"].get("/api/pos/shift/sessions/open/"))
        assert body[0]["operator_shifts"][0]["operator_id"] == str(world["operator"].pk)

    def test_a_closed_session_leaves_the_open_list(self, world):
        declare(world, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )
        assert rows(world["client"].get("/api/pos/shift/sessions/open/")) == []

    def test_forced_closures_have_a_standing_list(self, world):
        """Each is a drawer counted by somebody not responsible for it."""
        declare(world, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["supervisor"],
            declared_cash=cash("5000.00"), forced=True,
            reason="Operator left without closing", approver=world["supervisor"],
        )
        body = rows(world["client"].get("/api/pos/shift/reports/forced-closures/"))
        assert len(body) == 1
        assert body[0]["closure_type"] == "FORCED"
        assert "left without closing" in body[0]["closure_reason"]

    def test_variances_are_read_from_the_signed_snapshot(self, world):
        declare(world, "OPENING", "5000.00")
        declare(world, "CLOSING", "4900.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("4900.00")
        )
        body = rows(world["client"].get("/api/pos/shift/reports/variances/"))
        assert len(body) == 1
        assert body[0]["snapshot"]["variance"]["classification"] == "SHORT"

    def test_a_balanced_shift_is_not_a_variance(self, world):
        declare(world, "OPENING", "5000.00")
        declare(world, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )
        assert rows(world["client"].get("/api/pos/shift/reports/variances/")) == []

    def test_unapproved_cash_movements_can_be_filtered(self, world):
        CashMovement.all_objects.create(
            tenant=world["tenant"], register_session=world["session"], kind="CASH_OUT",
            amount=cash("500.00"), created_by=world["operator"],
        )
        body = rows(world["client"].get("/api/pos/shift/cash-movements/?unapproved=true"))
        assert len(body) == 1


class TestSessionReporting:
    def test_a_session_reports_whether_a_final_report_exists(self, world):
        """The report is the authority on closure, not the session row.

        A row edited back to OPEN must not read as reopened when its figures
        have already been signed off.
        """
        body = rows(world["client"].get("/api/pos/shift/sessions/"))
        assert body[0]["has_final_report"] is False

        declare(world, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["operator"], declared_cash=cash("5000.00")
        )
        body = rows(world["client"].get("/api/pos/shift/sessions/"))
        assert body[0]["has_final_report"] is True

    def test_a_forced_closure_is_visible_on_the_session_list(self, world):
        declare(world, "CLOSING", "5000.00")
        ShiftReportService.finalise_z(
            session=world["session"], actor=world["supervisor"],
            declared_cash=cash("5000.00"), forced=True, reason="Abandoned",
            approver=world["supervisor"],
        )
        body = rows(world["client"].get("/api/pos/shift/sessions/"))
        assert body[0]["forced_closure"] is True


# ─── isolation ───────────────────────────────────────────────────────────────


class TestIsolation:
    def test_another_tenants_registers_are_not_listed(self, world, db):
        other = Tenant.objects.create(name="Rival", slug="rival-shift")
        other_org = Organization.all_objects.create(tenant=other, code="ORG-R", name="Rival")
        other_branch = Location.all_objects.create(
            tenant=other, organization=other_org, code="MSA-R", name="Mombasa"
        )
        PosRegister.all_objects.create(
            tenant=other, location=other_branch, code="TILL-R", name="Theirs", state="AVAILABLE"
        )
        codes = {row["code"] for row in rows(world["client"].get("/api/pos/shift/registers/"))}
        assert "TILL-SA" in codes
        assert "TILL-R" not in codes

    def test_an_unauthenticated_caller_is_refused(self, db):
        assert APIClient().get("/api/pos/shift/sessions/").status_code in (401, 403)

    def test_every_collection_responds(self, world):
        for collection in (
            "registers", "business-days", "sessions", "shifts",
            "cash-declarations", "cash-movements", "reports", "reprints",
        ):
            assert world["client"].get(
                f"/api/pos/shift/{collection}/"
            ).status_code == 200, collection
