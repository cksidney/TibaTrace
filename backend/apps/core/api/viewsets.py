from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import TenantCapabilityPermission


class TenantModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.model.all_objects.none()
        return self.queryset.model.all_objects.filter(tenant_id=self.request.tenant_id)

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)

    def perform_update(self, serializer):
        if "tenant" in serializer.validated_data:
            raise ValidationError({"tenant": "Tenant ownership cannot be changed."})
        serializer.save()
