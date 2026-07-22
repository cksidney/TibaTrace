from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


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
