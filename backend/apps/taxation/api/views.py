"""Tenant-scoped fiscal monitoring over the single durable checkout outbox.

Configuration remains server-managed. This API never creates a second invoice
ledger, accepts secrets, activates a provider, or retries an uncertain invoice.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import log_audit
from apps.core.permissions import CapabilityPermission, PlatformOwnerRequired, TenantRequired
from apps.organizations.models import Location
from apps.prescription.fiscal import FiscalService
from apps.prescription.fiscal_models import FiscalSubmission
from apps.prescription.payment_connections import connection, vscu_config


def row_data(row):
    return {
        "id": str(row.pk), "branch_id": str(row.branch_id), "branch_name": row.branch.name,
        "source_kind": row.source_kind, "source_id": str(row.source_id),
        "invoice_number": row.invoice_number, "original_invoice_number": row.payload.get("orgInvcNo"),
        "status": row.status, "attempts": row.attempts, "error": row.error,
        "total": row.payload.get("totAmt"), "updated_at": row.updated_at,
        "receipt": row.response if row.status == "ACCEPTED" else None,
        "can_prepare": row.status == "NOT_CONFIGURED" and not row.payload,
    }


class FiscalView(APIView):
    def check_permissions(self, request):
        # Session/JWT middleware supplies selected scope. Force-authenticated
        # clients also retain their own tenant scope, like the POS collections.
        if not getattr(request, "tenant_id", None):
            request.tenant_id = getattr(request.user, "tenant_id", None)
        super().check_permissions(request)

    permission_classes = [permissions.IsAuthenticated, TenantRequired, CapabilityPermission]
    required_capabilities = ("pos.report.read", "pos.shift.manage", "platform.providers.manage")

    def rows(self, request):
        rows = FiscalSubmission.all_objects.filter(tenant_id=request.tenant_id).select_related("branch", "tenant")
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            from uuid import UUID
            try:
                branch_id = UUID(branch_id)
            except ValueError:
                raise DRFValidationError("Choose a valid branch.") from None
            rows = rows.filter(branch_id=branch_id)
        return rows


class TenantEtimsProfileView(FiscalView):
    def get(self, request):
        branches = []
        for branch in Location.all_objects.filter(tenant_id=request.tenant_id).select_related("tenant").order_by("code"):
            cfg = {}
            try:
                cfg = connection(tenant=branch.tenant, branch=branch, provider="VSCU")
                vscu_config(tenant=branch.tenant, branch=branch)
                ready, message = True, "Validated server configuration is enabled."
            except ValidationError:
                ready, message = False, "Registered VSCU configuration and validation are required."
            branches.append({"id": str(branch.pk), "code": branch.code, "name": branch.name,
                             "enabled": ready, "message": message,
                             "mapped_item_count": len(cfg.get("items", {})) if isinstance(cfg.get("items"), dict) else 0})
        return Response({"branches": branches, "configuration_mode": "SERVER_MANAGED"})


class FiscalReceiptListView(FiscalView):
    def get(self, request):
        rows = self.rows(request)
        state = request.query_params.get("status")
        if state:
            rows = rows.filter(status=state)
        return Response({"results": [row_data(row) for row in rows.order_by("-updated_at", "pk")[:100]], "count": rows.count()})


class FiscalReceiptDetailView(FiscalView):
    def get(self, request, pk):
        row = self.rows(request).filter(pk=pk).first()
        if not row:
            return Response({"detail": "Fiscal submission not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(row_data(row))


class FiscalReceiptRetryView(FiscalView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired, PlatformOwnerRequired]

    @transaction.atomic
    def post(self, request, pk):
        row = self.rows(request).select_for_update().filter(pk=pk).first()
        if not row:
            return Response({"detail": "Fiscal submission not found."}, status=status.HTTP_404_NOT_FOUND)
        if row.status != "NOT_CONFIGURED" or row.payload:
            return Response({"detail": "Only an unprepared invoice can be prepared. Reconcile uncertain outcomes with the registered VSCU; an existing invoice is never retransmitted here."}, status=status.HTTP_409_CONFLICT)
        try:
            row = FiscalService.prepare(row)
        except (ValidationError, ValueError) as exc:
            raise DRFValidationError(exc.messages if isinstance(exc, ValidationError) else "Review the server fiscal configuration.") from None
        log_audit(tenant_id=request.tenant_id, actor_id=request.user.pk, action="FISCAL_INVOICE_PREPARED",
                  model_name="prescription.FiscalSubmission", object_id=str(row.pk),
                  metadata={"invoice_number": row.invoice_number, "branch_id": str(row.branch_id)})
        # The existing worker sends the queued invoice after this transaction commits.
        return Response(row_data(row), status=status.HTTP_202_ACCEPTED)
