from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import TenantCapabilityPermission
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration
from apps.terminology.services import TerminologyService


class CodeSystemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FHIRCodeSystemRegistration
        fields = ("id", "version", "url", "name", "title", "content_mode", "concepts_json", "is_global")


class ValueSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = FHIRValueSetRegistration
        fields = ("id", "version", "url", "name", "title", "compose_json", "is_global")


class CodeSystemViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CodeSystemSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "terminology.read"
    write_capability = "terminology.manage"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FHIRCodeSystemRegistration.all_objects.none()
        return FHIRCodeSystemRegistration.objects.for_tenant(self.request.tenant_id)

    @action(detail=False, methods=["post"], url_path="validate-code")
    def validate_code(self, request):
        result = TerminologyService.validate_code(
            system=request.data.get("system", ""),
            code=request.data.get("code", ""),
            tenant_id=request.tenant_id,
            version=request.data.get("version"),
            display=request.data.get("display"),
        )
        return Response({"result": result.result, "display": result.display, "message": result.message})


class ValueSetViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ValueSetSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "terminology.read"
    write_capability = "terminology.manage"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FHIRValueSetRegistration.all_objects.none()
        return FHIRValueSetRegistration.objects.for_tenant(self.request.tenant_id)

    @action(detail=False, methods=["get"], url_path="expand")
    def expand(self, request):
        rows = TerminologyService.expand(
            url=request.query_params.get("url", ""),
            tenant_id=request.tenant_id,
            offset=request.query_params.get("offset", 0),
            count=request.query_params.get("count", 100),
        )
        return Response({"total": len(rows), "contains": rows})
