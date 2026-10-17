"""API Views for Taxation & KRA eTIMS."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import TenantRequired
from apps.taxation.api.serializers import (
    FiscalReceiptSerializer,
    FiscalSubmissionLogSerializer,
    TenantEtimsProfileSerializer,
)
from apps.taxation.models import FiscalReceipt, TenantEtimsProfile
from apps.taxation.services import FiscalizationPipeline
from apps.taxation.vscu_client import VscuClient
from apps.tenancy.models import Tenant


def _resolve_tenant(request) -> Tenant:
    tenant_id = (
        getattr(request, "tenant_id", None)
        or getattr(getattr(request, "tenant", None), "pk", None)
        or getattr(request.user, "tenant_id", None)
        or getattr(request.user, "active_tenant_id", None)
        or getattr(getattr(request.user, "active_tenant", None), "pk", None)
    )
    if tenant_id is None:
        raise DRFValidationError("No tenant context is available.")
    return Tenant.objects.get(pk=tenant_id)


class TenantEtimsProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def get(self, request):
        tenant = _resolve_tenant(request)
        profile, _ = TenantEtimsProfile.all_objects.get_or_create(tenant=tenant)
        serializer = TenantEtimsProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request):
        tenant = _resolve_tenant(request)
        profile, _ = TenantEtimsProfile.all_objects.get_or_create(tenant=tenant)
        serializer = TenantEtimsProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def put(self, request):
        return self.patch(request)


class EtimsTestConnectionView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def post(self, request):
        tenant = _resolve_tenant(request)
        profile = TenantEtimsProfile.all_objects.filter(tenant=tenant).first()
        if not profile or not profile.is_configured:
            return Response(
                {"error": "eTIMS profile is not configured. Please supply KRA PIN, Branch ID, and Device Serial."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = VscuClient(profile)
        result = client.check_server_time()
        return Response(result)


class EtimsInitializeView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def post(self, request):
        tenant = _resolve_tenant(request)
        profile = TenantEtimsProfile.all_objects.filter(tenant=tenant).first()
        if not profile or not profile.is_configured:
            return Response(
                {"error": "eTIMS profile is not configured. Please supply KRA PIN, Branch ID, and Device Serial."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client = VscuClient(profile)
        result = client.initialize_device()
        return Response(result)


class FiscalReceiptListView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def get(self, request):
        tenant = _resolve_tenant(request)
        qs = FiscalReceipt.all_objects.filter(tenant=tenant)

        submission_status = request.query_params.get("status")
        if submission_status:
            qs = qs.filter(submission_status=submission_status)

        receipt_type = request.query_params.get("type")
        if receipt_type:
            qs = qs.filter(receipt_type=receipt_type)

        invoice_no = request.query_params.get("invoice_number")
        if invoice_no and invoice_no.isdigit():
            qs = qs.filter(invoice_number=int(invoice_no))

        receipts = qs.order_by("-invoice_number")[:100]
        serializer = FiscalReceiptSerializer(receipts, many=True)
        return Response({"results": serializer.data, "count": qs.count()})


class FiscalReceiptDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def get(self, request, pk):
        tenant = _resolve_tenant(request)
        fiscal_receipt = FiscalReceipt.all_objects.filter(tenant=tenant, pk=pk).first()
        if not fiscal_receipt:
            return Response({"error": "Fiscal receipt not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = FiscalReceiptSerializer(fiscal_receipt)
        logs = fiscal_receipt.submission_logs.all().order_by("-created_at")
        log_serializer = FiscalSubmissionLogSerializer(logs, many=True)
        data = serializer.data
        data["submission_logs"] = log_serializer.data
        return Response(data)


class FiscalReceiptRetryView(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRequired]

    def post(self, request, pk):
        tenant = _resolve_tenant(request)
        fiscal_receipt = FiscalReceipt.all_objects.filter(tenant=tenant, pk=pk).first()
        if not fiscal_receipt:
            return Response({"error": "Fiscal receipt not found"}, status=status.HTTP_404_NOT_FOUND)

        profile = TenantEtimsProfile.all_objects.filter(tenant=tenant).first()
        if not profile or not profile.is_configured:
            return Response({"error": "eTIMS profile is not configured"}, status=status.HTTP_400_BAD_REQUEST)

        success = FiscalizationPipeline.transmit_to_vscu(fiscal_receipt, profile)
        return Response({
            "success": success,
            "submission_status": fiscal_receipt.submission_status,
            "last_error": fiscal_receipt.last_error,
            "attempt_count": fiscal_receipt.attempt_count,
        })
