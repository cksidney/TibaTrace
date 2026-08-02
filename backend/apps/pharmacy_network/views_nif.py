"""Premises verification NIF API views.

Platform Owner surface:
  GET  /api/v1/nif/premises-verifications/           — list all requests
  GET  /api/v1/nif/premises-verifications/{id}/      — detail
  POST /api/v1/nif/premises-verifications/{id}/review/ — approve/reject/clarify
  GET  /api/v1/nif/premises-verifications/{id}/snapshots/ — audit trail

Tenant surface:
  GET  /api/v1/premises-verifications/               — own tenant requests only
  POST /api/v1/premises-verifications/submit/        — submit evidence
  POST /api/v1/premises-verifications/{id}/clarify/  — respond to clarification
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.pharmacy_network.models import PharmacyProfile, PremisesVerificationRequest, PremisesVerificationSnapshot
from apps.pharmacy_network.serializers_nif import (
    PremisesVerificationRequestDetailSerializer,
    PremisesVerificationRequestListSerializer,
    PremisesVerificationReviewSerializer,
    PremisesVerificationSnapshotSerializer,
    PremisesVerificationSubmitSerializer,
)
from apps.pharmacy_network.verification_service import (
    approve_verification_request,
    reject_verification_request,
    request_clarification,
    submit_verification_request,
)
from apps.tenancy.models import Tenant


class TenantPremisesVerificationView(APIView):
    """Tenant-scoped premises verification API."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List this tenant's premises verification requests."""
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response({"detail": "Tenant context required."}, status=400)
        
        tenant = get_object_or_404(Tenant, pk=tenant_id)

        qs = PremisesVerificationRequest.all_objects.filter(
            tenant=tenant
        ).order_by("-created_at")[:50]
        serializer = PremisesVerificationRequestListSerializer(qs, many=True)
        return Response(serializer.data)


class TenantPremisesVerificationSubmitView(APIView):
    """Tenant submits premises verification evidence."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response({"detail": "Tenant context required."}, status=400)
            
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        
        serializer = PremisesVerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        profile = get_object_or_404(
            PharmacyProfile, id=serializer.validated_data["pharmacy_profile_id"], tenant=tenant
        )
        try:
            req = submit_verification_request(
                tenant_id=tenant.id,
                pharmacy_profile=profile,
                submitted_by=request.user,
                evidence_payload=serializer.validated_data["evidence_payload"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
            
        return Response(
            PremisesVerificationRequestListSerializer(req).data,
            status=status.HTTP_201_CREATED,
        )


class PlatformPremisesVerificationViewSet(ReadOnlyModelViewSet):
    """Platform Owner premises verification management."""

    permission_classes = [IsAuthenticated]
    serializer_class = PremisesVerificationRequestDetailSerializer

    def get_queryset(self):
        """Platform Owner sees all tenants' requests."""
        # In production: check request.user has platform.owner capability.
        return PremisesVerificationRequest.all_objects.select_related(
            "tenant", "pharmacy_profile", "submitted_by", "reviewed_by"
        ).order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        """Approve, reject, or request clarification on a premises request."""
        serializer = PremisesVerificationReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_name = serializer.validated_data["action"]
        req = get_object_or_404(PremisesVerificationRequest.all_objects, pk=pk)
        reviewer_notes = serializer.validated_data.get("reviewer_notes", "")
        verifier_declaration = serializer.validated_data.get("verifier_declaration", "")
        try:
            if action_name == "approve":
                result = approve_verification_request(
                    request=req,
                    actor=request.user,
                    reviewer_notes=reviewer_notes,
                    verifier_declaration=verifier_declaration,
                )
            elif action_name == "reject":
                result = reject_verification_request(
                    request=req,
                    actor=request.user,
                    reviewer_notes=reviewer_notes,
                )
            elif action_name == "request_clarification":
                result = request_clarification(
                    request=req,
                    actor=request.user,
                    reviewer_notes=reviewer_notes,
                )
            else:
                return Response({"detail": f"Unsupported action: {action_name}"}, status=400)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
            
        return Response(PremisesVerificationRequestDetailSerializer(result).data)

    @action(detail=True, methods=["get"], url_path="snapshots")
    def snapshots(self, request, pk=None):
        """Return immutable audit snapshots for a request."""
        req = get_object_or_404(PremisesVerificationRequest.all_objects, pk=pk)
        qs = PremisesVerificationSnapshot.objects.filter(
            verification_request=req
        ).order_by("-captured_at")
        serializer = PremisesVerificationSnapshotSerializer(qs, many=True)
        return Response(serializer.data)
