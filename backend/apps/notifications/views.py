"""Phase 14B Notification Engine DRF ViewSets."""
from __future__ import annotations

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.notifications.models import (
    IntegrationNotification,
    NotificationRolePreference,
    RegulatoryExpiryTrack,
)
from apps.notifications.serializers import (
    IntegrationNotificationSerializer,
    NotificationRolePreferenceSerializer,
    RegulatoryExpiryTrackSerializer,
)
from apps.notifications.service import evaluate_regulatory_expiries


class IntegrationNotificationViewSet(ReadOnlyModelViewSet):
    """View operational integration notifications."""

    permission_classes = [IsAuthenticated]
    serializer_class = IntegrationNotificationSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id:
            return IntegrationNotification.all_objects.filter(tenant_id=tenant_id)
        return IntegrationNotification.all_objects.all()

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.is_read = True
        notif.read_at = timezone.now()
        notif.read_by = request.user
        notif.save(update_fields=["is_read", "read_at", "read_by", "updated_at"])
        return Response(IntegrationNotificationSerializer(notif).data)

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        notif = self.get_object()
        notif.is_acknowledged = True
        notif.acknowledged_at = timezone.now()
        notif.acknowledged_by = request.user
        notif.save(update_fields=["is_acknowledged", "acknowledged_at", "acknowledged_by", "updated_at"])
        return Response(IntegrationNotificationSerializer(notif).data)


class NotificationRolePreferenceViewSet(ModelViewSet):
    """Platform Owner / Compliance: manage role notification preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationRolePreferenceSerializer
    queryset = NotificationRolePreference.objects.all()


class RegulatoryExpiryTrackViewSet(ModelViewSet):
    """Manage and evaluate regulatory expiries."""

    permission_classes = [IsAuthenticated]
    serializer_class = RegulatoryExpiryTrackSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id:
            return RegulatoryExpiryTrack.all_objects.filter(tenant_id=tenant_id)
        return RegulatoryExpiryTrack.all_objects.all()

    @action(detail=False, methods=["post"], url_path="evaluate")
    def evaluate(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        tracks = evaluate_regulatory_expiries(tenant_id=tenant_id)
        return Response({
            "detail": f"Evaluated regulatory expiries. {len(tracks)} threshold notifications triggered.",
            "processed_count": len(tracks),
        })
