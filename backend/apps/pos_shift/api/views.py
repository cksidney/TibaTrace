"""Shift, cash-control and X/Z report workbench.

Read-only. Opening a register, closing one, declaring cash and generating a Z
each run through ShiftReportService, which enforces that exactly one Z exists
per session, that a forced closure names an approver, and that closure
preconditions are met. An endpoint that could write those columns would be a
second way to close a till with none of it.

Reports are served from their stored snapshot. HQ never recalculates a Z: it is
what somebody counted, signed and banked against, and re-deriving it from
current data would restate history while the operator holds the printed copy.
"""
from __future__ import annotations

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

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
from apps.pos_shift.authority import RegisterAuthorityService
from apps.prescription.pos_dispensing_api.serializers import PosDeviceHealthRecordSerializer

from .serializers import (
    BusinessDaySerializer,
    CashDeclarationSerializer,
    CashMovementSerializer,
    OperatorShiftSerializer,
    PosRegisterSerializer,
    RegisterSessionSerializer,
    ShiftReportReprintSerializer,
    ShiftReportSerializer,
)


class TenantScopedReadOnly(viewsets.ReadOnlyModelViewSet):
    """Read-only, tenant-scoped by construction."""

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def get_queryset(self):
        request = self.request
        tenant_id = (
            getattr(request, "tenant_id", None)
            or getattr(getattr(request, "tenant", None), "pk", None)
            or getattr(request.user, "tenant_id", None)
        )
        if tenant_id is None:
            return self.model.all_objects.none()
        return self.model.all_objects.filter(tenant_id=tenant_id)


class PosRegisterViewSet(TenantScopedReadOnly):
    model = PosRegister
    serializer_class = PosRegisterSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("location")

    @action(detail=False, methods=["get"], url_path="runtime")
    def runtime(self, request):
        tenant_id = (
            getattr(request, "tenant_id", None)
            or getattr(getattr(request, "tenant", None), "pk", None)
            or getattr(request.user, "tenant_id", None)
        )
        if tenant_id is None:
            return Response(RegisterAuthorityService._unassigned("No tenant context is available."))
        from apps.tenancy.models import Tenant

        tenant = Tenant.objects.get(pk=tenant_id)
        status = RegisterAuthorityService.runtime_status(
            tenant=tenant,
            actor=request.user,
            device_id=request.query_params.get("device_id", ""),
        )
        return Response(
            {
                "readiness": status["readiness"],
                "register": PosRegisterSerializer(status["register"]).data if status["register"] else None,
                "business_day": BusinessDaySerializer(status["business_day"]).data if status["business_day"] else None,
                "register_session": RegisterSessionSerializer(status["register_session"]).data if status["register_session"] else None,
                "operator_shift": OperatorShiftSerializer(status["operator_shift"]).data if status["operator_shift"] else None,
                "device_health": PosDeviceHealthRecordSerializer(status["device_health"]).data if status["device_health"] else None,
                "notices": status["notices"],
                "allowed_actions": status["allowed_actions"],
                "closure_eligibility": status["closure_eligibility"],
            }
        )


class BusinessDayViewSet(TenantScopedReadOnly):
    model = BusinessDay
    serializer_class = BusinessDaySerializer

    def get_queryset(self):
        return super().get_queryset().select_related("location")


class RegisterSessionViewSet(TenantScopedReadOnly):
    model = RegisterSession
    serializer_class = RegisterSessionSerializer

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .select_related("register", "business_day", "opened_by", "closed_by")
            .prefetch_related("operator_shifts")
        )
        params = self.request.query_params
        if params.get("state"):
            queryset = queryset.filter(state=params["state"])
        if params.get("register"):
            queryset = queryset.filter(register_id=params["register"])
        return queryset

    @action(detail=False, methods=["get"], url_path="open")
    def open_sessions(self, request):
        """Registers currently trading.

        The list somebody checks at close of business to find a till nobody
        closed -- which is otherwise discovered the next morning, after a night
        of unreconciled cash.
        """
        queryset = self.get_queryset().filter(state="OPEN")
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="unclosed")
    def unclosed(self, request):
        """Sessions closed without a Z, or left open on a finished day.

        The report is the authority on closure, so a session row saying CLOSED
        with no Z is an exception rather than a completed shift.
        """
        queryset = [
            session
            for session in self.get_queryset()
            if not ShiftReport.all_objects.filter(
                tenant_id=session.tenant_id,
                register_session=session,
                report_type=ShiftReport.TYPE_Z,
            ).exists()
            and session.state in {"CLOSED", "CLOSING"}
        ]
        return Response(self.get_serializer(queryset, many=True).data)


class OperatorShiftViewSet(TenantScopedReadOnly):
    model = OperatorShift
    serializer_class = OperatorShiftSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("operator", "handed_over_to")


class CashDeclarationViewSet(TenantScopedReadOnly):
    model = CashDeclaration
    serializer_class = CashDeclarationSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("declared_by")
        session = self.request.query_params.get("session")
        if session:
            queryset = queryset.filter(register_session_id=session)
        return queryset


class CashMovementViewSet(TenantScopedReadOnly):
    model = CashMovement
    serializer_class = CashMovementSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("created_by", "approved_by")
        params = self.request.query_params
        if params.get("session"):
            queryset = queryset.filter(register_session_id=params["session"])
        if params.get("unapproved") == "true":
            queryset = queryset.filter(approved_at__isnull=True)
        return queryset


class ShiftReportViewSet(TenantScopedReadOnly):
    """X and Z reports, served from their frozen snapshots."""

    model = ShiftReport
    serializer_class = ShiftReportSerializer

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .select_related("register_session__register", "business_day", "generated_by")
            .prefetch_related("reprints")
        )
        params = self.request.query_params
        if params.get("type"):
            queryset = queryset.filter(report_type=params["type"].upper())
        if params.get("business_date"):
            queryset = queryset.filter(business_day__business_date=params["business_date"])
        return queryset

    @action(detail=False, methods=["get"], url_path="z")
    def final_reports(self, request):
        queryset = self.get_queryset().filter(report_type=ShiftReport.TYPE_Z)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="forced-closures")
    def forced_closures(self, request):
        """Closures performed by somebody other than the accountable operator.

        A standing review list rather than a filter somebody has to think to
        apply: each one is a drawer counted by a person who was not responsible
        for it.
        """
        queryset = self.get_queryset().filter(closure_type=ShiftReport.CLOSURE_FORCED)
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="variances")
    def variances(self, request):
        """Z reports whose counted cash did not match expected.

        Read from each report's frozen snapshot rather than recomputed, so the
        figure shown is the one that was signed.
        """
        reports = []
        for report in self.get_queryset().filter(report_type=ShiftReport.TYPE_Z):
            variance = (report.snapshot or {}).get("variance") or {}
            if variance.get("requires_explanation"):
                reports.append(report)
        return Response(self.get_serializer(reports, many=True).data)


class ShiftReportReprintViewSet(TenantScopedReadOnly):
    model = ShiftReportReprint
    serializer_class = ShiftReportReprintSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("report", "reprinted_by")
