from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.audit.models import AuditEvent
from apps.core.permissions import TenantCapabilityPermission


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = "__all__"


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "audit.read"
    write_capability = "audit.write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AuditEvent.all_objects.none()
        return AuditEvent.all_objects.filter(tenant_id=self.request.tenant_id).order_by("-created_at")
