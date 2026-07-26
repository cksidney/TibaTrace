from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.tenancy.api.serializers import TenantSerializer, TenantSuspensionSerializer
from apps.tenancy.models import Tenant
from apps.tenancy.services import TenantManagementService


def _error_payload(exc: DjangoValidationError) -> dict:
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"detail": list(getattr(exc, "messages", [str(exc)]))}


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_platform_admin:
            return Tenant.objects.all().order_by("name", "id")
        if user.tenant_id:
            return Tenant.objects.filter(pk=user.tenant_id)
        return Tenant.objects.none()

    def _require_platform_admin(self):
        user = self.request.user
        if not (user.is_superuser or user.is_platform_admin):
            raise PermissionDenied("Tenant management is restricted to platform administrators.")

    def create(self, request, *args, **kwargs):
        self._require_platform_admin()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tenant = TenantManagementService.create_tenant(**serializer.validated_data)
        except DjangoValidationError as exc:
            return Response(_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(tenant).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        self._require_platform_admin()
        tenant = self.get_object()
        serializer = self.get_serializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        values = {
            "name": serializer.validated_data.get("name", tenant.name),
            "slug": serializer.validated_data.get("slug", tenant.slug),
            "country_code": serializer.validated_data.get("country_code", tenant.country_code),
            "time_zone": serializer.validated_data.get("time_zone", tenant.time_zone),
            "metadata": serializer.validated_data.get("metadata", tenant.metadata),
        }
        try:
            tenant = TenantManagementService.update_tenant(tenant=tenant, **values)
        except DjangoValidationError as exc:
            return Response(_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self._require_platform_admin()
        serializer = TenantSuspensionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tenant = TenantManagementService.suspend_tenant(
                tenant=self.get_object(),
                reason=serializer.validated_data["reason"],
            )
        except DjangoValidationError as exc:
            return Response(_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(tenant).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        self._require_platform_admin()
        tenant = TenantManagementService.activate_tenant(tenant=self.get_object())
        return Response(self.get_serializer(tenant).data)
