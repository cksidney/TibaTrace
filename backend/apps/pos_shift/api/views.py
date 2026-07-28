"""Shift, cash-control and X/Z report workbench.

Collections are read-only. The small set of controlled command endpoints run
through operation services, which enforce one Z per session, immutable cash
declarations, device-bound register authority, and closure preconditions.

Reports are served from their stored snapshot. HQ never recalculates a Z: it is
what somebody counted, signed and banked against, and re-deriving it from
current data would restate history while the operator holds the printed copy.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.pos_shift.authority import RegisterAuthorityService
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
from apps.pos_shift.operations import (
    CashMovementService,
    OperatorShiftService,
    RegisterOpeningService,
    RegisterReportService,
)
from apps.prescription.pos_dispensing_api.serializers import PosDeviceHealthRecordSerializer

from .serializers import (
    BusinessDaySerializer,
    CashDeclarationSerializer,
    CashMovementRequestSerializer,
    CashMovementSerializer,
    OperatorShiftActionRequestSerializer,
    OperatorShiftSerializer,
    PosRegisterSerializer,
    RegisterCloseRequestSerializer,
    RegisterOpeningRequestSerializer,
    RegisterSessionSerializer,
    ReportRequestSerializer,
    ShiftReportReprintSerializer,
    ShiftReportSerializer,
)


def _tenant(request):
    tenant_id = (
        getattr(request, "tenant_id", None)
        or getattr(getattr(request, "tenant", None), "pk", None)
        or getattr(request.user, "tenant_id", None)
    )
    if tenant_id is None:
        raise DRFValidationError("No tenant context is available.")
    from apps.tenancy.models import Tenant

    return Tenant.objects.get(pk=tenant_id)


def _run(operation):
    try:
        return operation()
    except ValidationError as error:
        raise DRFValidationError(error.messages) from error


class TenantScopedViewSet(viewsets.ReadOnlyModelViewSet):
    """Tenant-scoped collections with explicit controlled commands."""

    permission_classes = [permissions.IsAuthenticated]
    model = None

    def _tenant_id(self):
        """The caller's tenant, from the request or the authenticated user.

        Shared with nested prefetches, which must filter explicitly rather than
        leaning on the tenant-strict manager and the thread-local behind it.
        """
        request = self.request
        return (
            getattr(request, "tenant_id", None)
            or getattr(getattr(request, "tenant", None), "pk", None)
            or getattr(request.user, "tenant_id", None)
        )

    def get_queryset(self):
        tenant_id = self._tenant_id()
        if tenant_id is None:
            return self.model.all_objects.none()
        return self.model.all_objects.filter(tenant_id=tenant_id)


class PosRegisterViewSet(TenantScopedViewSet):
    model = PosRegister
    serializer_class = PosRegisterSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("location")

    @action(detail=False, methods=["get"], url_path="runtime")
    def runtime(self, request):
        try:
            tenant = _tenant(request)
        except DRFValidationError:
            return Response(RegisterAuthorityService._unassigned("No tenant context is available."))
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

    @action(detail=True, methods=["post"], url_path="open")
    def open_register(self, request, pk=None):
        register = self.get_object()
        serializer = RegisterOpeningRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = _tenant(request)
        session, operator_shift, declaration = _run(
            lambda: RegisterOpeningService.open(
                tenant=tenant,
                register_id=register.pk,
                actor=request.user,
                device_id=data["device_id"],
                opening_amount=data["opening_amount"],
                denominations=data["denominations"],
            )
        )
        return Response(
            {
                "register": PosRegisterSerializer(register).data,
                "register_session": RegisterSessionSerializer(session).data,
                "operator_shift": OperatorShiftSerializer(operator_shift).data,
                "opening_declaration": CashDeclarationSerializer(declaration).data,
            },
            status=201,
        )

    @action(detail=True, methods=["post"], url_path="x-report")
    def x_report(self, request, pk=None):
        register = self.get_object()
        serializer = ReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if register.device_id != data["device_id"]:
            raise DRFValidationError("The selected register is not assigned to this device.")
        if register.state == "CLOSED":
            existing = (
                ShiftReport.all_objects.filter(
                    tenant_id=register.tenant_id,
                    register_session__register=register,
                    report_type=ShiftReport.TYPE_Z,
                )
                .order_by("-generated_at")
                .first()
            )
            if existing is not None:
                return Response(ShiftReportSerializer(existing).data)
        report = _run(
            lambda: RegisterReportService.generate_x(
                tenant=_tenant(request),
                branch=register.location,
                actor=request.user,
                device_id=data["device_id"],
            )
        )
        return Response(ShiftReportSerializer(report).data, status=201)

    @action(detail=True, methods=["post"], url_path="close")
    def close_register(self, request, pk=None):
        register = self.get_object()
        serializer = RegisterCloseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if register.device_id != data["device_id"]:
            raise DRFValidationError("The selected register is not assigned to this device.")
        existing = (
            ShiftReport.all_objects.filter(
                tenant_id=register.tenant_id,
                register_session__register=register,
                report_type=ShiftReport.TYPE_Z,
            )
            .order_by("-generated_at")
            .first()
        )
        if existing is not None:
            return Response(ShiftReportSerializer(existing).data)
        report = _run(
            lambda: RegisterReportService.finalise_z(
                tenant=_tenant(request),
                branch=register.location,
                actor=request.user,
                device_id=data["device_id"],
                declared_amount=data["declared_amount"],
                denominations=data["denominations"],
                reason=data["reason"],
            )
        )
        return Response(ShiftReportSerializer(report).data, status=201)


class BusinessDayViewSet(TenantScopedViewSet):
    model = BusinessDay
    serializer_class = BusinessDaySerializer

    def get_queryset(self):
        return super().get_queryset().select_related("location")


class RegisterSessionViewSet(TenantScopedViewSet):
    model = RegisterSession
    serializer_class = RegisterSessionSerializer

    def get_queryset(self):
        queryset = (
            super().get_queryset()
            .select_related("register", "business_day", "opened_by", "closed_by")
            # An explicit prefetch, not the bare related name.
            #
            # `operator_shifts` resolves through OperatorShift's default manager,
            # which is tenant-strict: with no tenant id on the thread it returns
            # nothing, and the session then serialises with no accountable
            # operator at all. The session's own queryset already filters by
            # tenant explicitly, so the outer list looked right while the nested
            # one silently emptied -- a till showing an open session that nobody
            # is answerable for.
            .prefetch_related(
                Prefetch(
                    "operator_shifts",
                    queryset=OperatorShift.all_objects.filter(
                        tenant_id=self._tenant_id()
                    ).select_related("operator"),
                )
            )
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


class OperatorShiftViewSet(TenantScopedViewSet):
    model = OperatorShift
    serializer_class = OperatorShiftSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("operator", "handed_over_to")

    @action(detail=True, methods=["post"], url_path="request-handover")
    def request_handover(self, request, pk=None):
        serializer = OperatorShiftActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        operator_shift = _run(
            lambda: OperatorShiftService.request_handover(
                tenant=_tenant(request),
                actor=request.user,
                device_id=data["device_id"],
                operator_shift_id=pk,
                reason=data["reason"],
            )
        )
        return Response(OperatorShiftSerializer(operator_shift).data)

    @action(detail=True, methods=["post"], url_path="cancel-handover")
    def cancel_handover(self, request, pk=None):
        serializer = OperatorShiftActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        operator_shift = _run(
            lambda: OperatorShiftService.cancel_handover(
                tenant=_tenant(request),
                actor=request.user,
                device_id=data["device_id"],
                operator_shift_id=pk,
            )
        )
        return Response(OperatorShiftSerializer(operator_shift).data)

    @action(detail=True, methods=["post"], url_path="accept-handover")
    def accept_handover(self, request, pk=None):
        serializer = OperatorShiftActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        outgoing, incoming = _run(
            lambda: OperatorShiftService.accept_handover(
                tenant=_tenant(request),
                actor=request.user,
                device_id=data["device_id"],
                operator_shift_id=pk,
            )
        )
        return Response(
            {
                "outgoing_shift": OperatorShiftSerializer(outgoing).data,
                "operator_shift": OperatorShiftSerializer(incoming).data,
            },
            status=201,
        )


class CashDeclarationViewSet(TenantScopedViewSet):
    model = CashDeclaration
    serializer_class = CashDeclarationSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("declared_by")
        session = self.request.query_params.get("session")
        if session:
            queryset = queryset.filter(register_session_id=session)
        return queryset


class CashMovementViewSet(TenantScopedViewSet):
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

    @action(detail=False, methods=["post"], url_path="record")
    def record(self, request):
        serializer = CashMovementRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = _tenant(request)
        register = PosRegister.all_objects.filter(tenant=tenant, device_id=data["device_id"]).select_related("location").first()
        if register is None:
            raise DRFValidationError("This device is not assigned to a register.")
        movement = _run(
            lambda: CashMovementService.record(
                tenant=tenant,
                branch=register.location,
                actor=request.user,
                device_id=data["device_id"],
                kind=data["kind"],
                amount=data["amount"],
                reason_code=data["reason_code"],
                description=data["description"],
                reference=data["reference"],
            )
        )
        return Response(CashMovementSerializer(movement).data, status=201)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        movement = self.get_object()
        approved = _run(
            lambda: CashMovementService.approve(
                movement=movement,
                actor=request.user,
            )
        )
        return Response(CashMovementSerializer(approved).data)


class ShiftReportViewSet(TenantScopedViewSet):
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


class ShiftReportReprintViewSet(TenantScopedViewSet):
    model = ShiftReportReprint
    serializer_class = ShiftReportReprintSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("report", "reprinted_by")
