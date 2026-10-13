"""Regulatory alert and recall API views.

Platform Owner:
  - ingest alerts;
  - activate alerts;
  - manage match candidates;
  - quarantine tenant stock;
  - view all tenant impacts.

Tenant:
  - view own impacts;
  - record recall actions;
  - request closure (with evidence).
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.core.permissions import PlatformOwnerRequired
from apps.inventory.recalls.models import (
    RegulatoryAlert,
    RegulatoryTenantImpact,
)
from apps.inventory.recalls.serializers import (
    RegulatoryActionCreateSerializer,
    RegulatoryActionReadSerializer,
    RegulatoryAlertDetailSerializer,
    RegulatoryAlertIngestSerializer,
    RegulatoryAlertListSerializer,
    RegulatoryAlertVersionSerializer,
    RegulatoryClosureCreateSerializer,
    RegulatoryClosureSerializer,
    RegulatoryQuarantineSerializer,
    RegulatoryTenantImpactSerializer,
    RegulatoryTenantQuarantineSerializer,
)
from apps.inventory.recalls.services import (
    activate_alert,
    close_alert_for_tenant,
    ingest_alert,
    quarantine_tenant_stock,
    record_regulatory_action,
)

logger = logging.getLogger(__name__)


class RecallTenantPermission(BasePermission):
    def has_permission(self, request, view):
        tenant_id = getattr(request, "tenant_id", None)
        capabilities = ("recalls.manage", "compliance.officer")
        if request.method in SAFE_METHODS:
            capabilities += ("recalls.read", "inventory.read", "inventory.manage")
        return bool(tenant_id and any(request.user.has_capability(cap, tenant_id=tenant_id) for cap in capabilities))


class PlatformRegulatoryAlertViewSet(ModelViewSet):
    """Platform Owner: manage regulatory alerts."""

    permission_classes = [IsAuthenticated, PlatformOwnerRequired]
    # Lifecycle changes belong to the governed actions. An inherited DELETE or
    # generic update must never erase an alert and its cross-tenant evidence.
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = RegulatoryAlertDetailSerializer
    queryset = RegulatoryAlert.objects.all().order_by("-ingested_at")

    def get_serializer_class(self):
        if self.action == "list":
            return RegulatoryAlertListSerializer
        return RegulatoryAlertDetailSerializer

    def create(self, request, *args, **kwargs):
        """Ingest a new regulatory alert (draft state)."""
        serializer = RegulatoryAlertIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            alert = ingest_alert(actor=request.user, **serializer.validated_data)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            RegulatoryAlertDetailSerializer(alert).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """Activate a draft alert."""
        alert = self.get_object()
        try:
            result = activate_alert(alert=alert, actor=request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RegulatoryAlertDetailSerializer(result).data)

    @action(detail=True, methods=["get"], url_path="versions")
    def versions(self, request, pk=None):
        alert = self.get_object()
        qs = alert.versions.all().order_by("-version_number")
        return Response(RegulatoryAlertVersionSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="impacts")
    def impacts(self, request, pk=None):
        alert = self.get_object()
        qs = alert.tenant_impacts.all()
        return Response(RegulatoryTenantImpactSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="quarantine")
    def quarantine(self, request, pk=None):
        """Quarantine affected stock for a specific tenant."""
        alert = self.get_object()
        serializer = RegulatoryQuarantineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            impact = quarantine_tenant_stock(
                alert=alert,
                tenant_id=serializer.validated_data["tenant_id"],
                actor=request.user,
                affected_batches=serializer.validated_data["affected_batches"],
                prior_dispense_trace_required=serializer.validated_data["prior_dispense_trace_required"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RegulatoryTenantImpactSerializer(impact).data)


class TenantRegulatoryImpactViewSet(ReadOnlyModelViewSet):
    """Tenant: view own regulatory impacts."""

    permission_classes = [IsAuthenticated, RecallTenantPermission]
    serializer_class = RegulatoryTenantImpactSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return RegulatoryTenantImpact.all_objects.none()
        return RegulatoryTenantImpact.all_objects.filter(tenant_id=tenant_id).select_related(
            "alert", "tenant"
        ).prefetch_related("actions__performed_by").order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="quarantine")
    def quarantine(self, request, pk=None):
        impact = self.get_object()
        serializer = RegulatoryTenantQuarantineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            impact = quarantine_tenant_stock(
                alert=impact.alert,
                tenant_id=impact.tenant_id,
                actor=request.user,
                affected_batches=serializer.validated_data["affected_batches"],
                prior_dispense_trace_required=serializer.validated_data["prior_dispense_trace_required"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RegulatoryTenantImpactSerializer(impact).data)

    @action(detail=True, methods=["post"], url_path="actions")
    def add_action(self, request, pk=None):
        impact = self.get_object()
        serializer = RegulatoryActionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            action_obj = record_regulatory_action(
                impact=impact,
                actor=request.user,
                action_type=serializer.validated_data["action_type"],
                notes=serializer.validated_data.get("notes", ""),
                evidence_payload=serializer.validated_data.get("evidence_payload", {}),
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RegulatoryActionReadSerializer(action_obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        impact = self.get_object()
        serializer = RegulatoryClosureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            closure = close_alert_for_tenant(
                impact=impact,
                actor=request.user,
                regulator_withdrawal_reference=serializer.validated_data["regulator_withdrawal_reference"],
                compliance_review_notes=serializer.validated_data["compliance_review_notes"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RegulatoryClosureSerializer(closure).data)
