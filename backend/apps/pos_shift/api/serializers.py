"""Read serialisers for the shift and cash-control workbench.

Reports are served from their stored snapshot and never recomputed. A Z report
is what somebody counted, signed and banked against; re-deriving it from today's
transaction table would quietly restate history, and the operator holds the
printed copy. The snapshot is returned verbatim.

Cash figures are strings, not floats. JSON has one number type and it is binary
floating point, so serialising a Decimal as a number is how 22000.00 arrives as
21999.999999999996 and a reconciliation that balanced in the database stops
balancing on the screen.
"""
from __future__ import annotations

from rest_framework import serializers

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


class MoneyField(serializers.Field):
    """A decimal amount, serialised as a string.

    JSON numbers are binary floats. A till total that round-trips through one
    stops matching the drawer.
    """

    def to_representation(self, value):
        return str(value)


class PosRegisterSerializer(serializers.ModelSerializer):
    branch_code = serializers.CharField(source="location.code", read_only=True)
    expected_float = MoneyField()

    class Meta:
        model = PosRegister
        fields = [
            "id", "code", "name", "branch_code", "device_id", "currency",
            "state", "expected_float", "last_synchronised_at",
        ]


class BusinessDaySerializer(serializers.ModelSerializer):
    branch_code = serializers.CharField(source="location.code", read_only=True)
    accepts_transactions = serializers.BooleanField(read_only=True)

    class Meta:
        model = BusinessDay
        fields = [
            "id", "branch_code", "business_date", "state", "opened_at",
            "closed_at", "accepts_transactions", "reopen_reason",
        ]


class OperatorShiftSerializer(serializers.ModelSerializer):
    operator_username = serializers.CharField(source="operator.username", read_only=True)
    handed_over_to_username = serializers.SerializerMethodField()

    class Meta:
        model = OperatorShift
        fields = [
            "id", "operator_username", "state", "started_at", "ended_at",
            "handed_over_to_username", "close_reason",
        ]

    def get_handed_over_to_username(self, shift) -> str:
        return getattr(shift.handed_over_to, "username", "") or ""


class RegisterSessionSerializer(serializers.ModelSerializer):
    register_code = serializers.CharField(source="register.code", read_only=True)
    business_date = serializers.DateField(source="business_day.business_date", read_only=True)
    opened_by_username = serializers.CharField(source="opened_by.username", read_only=True)
    closed_by_username = serializers.SerializerMethodField()
    has_final_report = serializers.SerializerMethodField()
    operator_shifts = OperatorShiftSerializer(many=True, read_only=True)

    class Meta:
        model = RegisterSession
        fields = [
            "id", "register_code", "business_date", "state",
            "opened_at", "opened_by_username", "closed_at", "closed_by_username",
            # Surfaced because a forced closure is somebody overriding the
            # person accountable for the drawer, and it should be visible in a
            # list rather than only in a detail view.
            "forced_closure", "forced_closure_reason",
            "has_final_report", "operator_shifts",
        ]

    def get_closed_by_username(self, session) -> str:
        return getattr(session.closed_by, "username", "") or ""

    def get_has_final_report(self, session) -> bool:
        """Whether a Z exists.

        The report is the authority on closure, not the session row: a session
        edited back to OPEN must not read as reopened when its figures have
        already been signed off.

        Queried through all_objects with an explicit tenant filter rather than
        the related manager. The related manager is tenant-strict and returns
        nothing when no tenant context is set, which made a closed session
        report as having no Z -- a closed till reading as open, which is the
        dangerous direction for this particular flag.
        """
        return ShiftReport.all_objects.filter(
            tenant_id=session.tenant_id,
            register_session=session,
            report_type=ShiftReport.TYPE_Z,
        ).exists()


class CashDeclarationSerializer(serializers.ModelSerializer):
    declared_amount = MoneyField()
    declared_by_username = serializers.CharField(source="declared_by.username", read_only=True)
    is_confirmed = serializers.BooleanField(read_only=True)

    class Meta:
        model = CashDeclaration
        fields = [
            "id", "kind", "declared_amount", "currency", "denominations",
            # The attempt number matters: a recount is a second declaration, and
            # seeing only the latest hides that the first one differed.
            "attempt", "declared_by_username", "confirmed_at", "is_confirmed", "reason",
        ]


class CashMovementSerializer(serializers.ModelSerializer):
    amount = MoneyField()
    signed_amount = MoneyField(read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    approved_by_username = serializers.SerializerMethodField()

    class Meta:
        model = CashMovement
        fields = [
            "id", "kind", "amount", "signed_amount", "affects_expected_cash",
            "currency", "reason_code", "description", "reference",
            "created_by_username", "approved_by_username", "approved_at", "created_at",
        ]

    def get_approved_by_username(self, movement) -> str:
        return getattr(movement.approved_by, "username", "") or ""


class ShiftReportSerializer(serializers.ModelSerializer):
    register_code = serializers.CharField(
        source="register_session.register.code", read_only=True
    )
    business_date = serializers.DateField(source="business_day.business_date", read_only=True)
    generated_by_username = serializers.CharField(
        source="generated_by.username", read_only=True
    )
    approved_by_username = serializers.SerializerMethodField()
    reprint_count = serializers.SerializerMethodField()

    class Meta:
        model = ShiftReport
        fields = [
            "id", "report_number", "report_type", "register_code", "business_date",
            "period_start", "generated_at", "generated_by_username",
            "closure_type", "closure_reason", "approved_by_username",
            # Verbatim. HQ reads what was counted and signed, never a
            # recomputation against today's data.
            "snapshot", "exceptions", "reprint_count",
        ]

    def get_approved_by_username(self, report) -> str:
        return getattr(report.approved_by, "username", "") or ""

    def get_reprint_count(self, report) -> int:
        return report.reprints.count()


class ShiftReportReprintSerializer(serializers.ModelSerializer):
    report_number = serializers.CharField(source="report.report_number", read_only=True)
    reprinted_by_username = serializers.CharField(
        source="reprinted_by.username", read_only=True
    )

    class Meta:
        model = ShiftReportReprint
        fields = [
            # The original number, never a new one: a reprint presented as a
            # separate closure is how a day's takings get banked twice.
            "id", "report_number", "copy_number", "reason",
            "reprinted_by_username", "reprinted_at", "printer",
        ]
