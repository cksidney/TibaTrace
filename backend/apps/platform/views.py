from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.admin_shell import (
    build_hq_dashboard_context,
    build_hq_workspace_context,
)


def pos_terminal_view(request):
    """Serve the POS terminal shell.

    `demo_tools_enabled` gates the seed-demo buttons. Seeding puts fictional
    patients, with dispensing numbers, into the working queue -- which is not
    something a production till should be able to do from its own header.
    """
    from django.conf import settings

    return render(
        request,
        "pos/pos.html",
        {
            "demo_tools_enabled": bool(settings.DEBUG),
            "product_version": settings.DAWATRACE_VERSION,
        },
    )


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        database_ok = cursor.fetchone() == (1,)
    return JsonResponse(
        {
            "status": "ok" if database_ok else "degraded",
            "product": settings.DAWATRACE_PRODUCT_NAME,
            "vendor": settings.DAWATRACE_VENDOR,
            "fhir_version": settings.FHIR_VERSION,
        },
        status=200 if database_ok else 503,
    )


class PlatformInfoSerializer(serializers.Serializer):
    product = serializers.CharField()
    vendor = serializers.CharField()
    api = serializers.CharField()
    tenant_id = serializers.CharField()


class PlatformInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=PlatformInfoSerializer)
    def get(self, request):
        return Response(
            {
                "product": settings.DAWATRACE_PRODUCT_NAME,
                "vendor": settings.DAWATRACE_VENDOR,
                "api": "DawaTrace API",
                "tenant_id": str(getattr(request, "tenant_id", "")),
            }
        )


class HQOverviewSerializer(serializers.Serializer):
    attention_items = serializers.ListField(child=serializers.DictField())
    data_summary = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.DateTimeField()
    is_platform_overview = serializers.BooleanField()
    metrics = serializers.ListField(child=serializers.DictField())
    network_items = serializers.ListField(child=serializers.DictField())
    scope_description = serializers.CharField()
    scope_label = serializers.CharField()
    tenant_id = serializers.CharField(allow_blank=True)
    tenant_name = serializers.CharField()
    user_name = serializers.CharField()


class HQOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=HQOverviewSerializer)
    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        return Response(build_hq_dashboard_context(request.user, tenant_id))


class HQWorkspaceSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    business_modules = serializers.ListField(child=serializers.DictField())
    people = serializers.DictField()
    catalogue = serializers.DictField()
    commerce = serializers.DictField()
    governance = serializers.DictField()


class HQWorkspaceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=HQWorkspaceSerializer)
    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        if not tenant_id and not (
            request.user.is_superuser or request.user.is_platform_admin
        ):
            return Response(
                {"detail": "A tenant workspace is required."},
                status=403,
            )
        return Response(build_hq_workspace_context(tenant_id))
