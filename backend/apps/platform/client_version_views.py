"""Authenticated POS clients ask HQ whether their binary is still aligned."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.client_version import (
    client_build_from_request,
    evaluate_client_version,
    normalize_platform,
)


class PosClientVersionCheckView(APIView):
    """Daily (and Sync Centre) client ↔ HQ release alignment check.

    Requires an authenticated POS / HQ session. Installer downloads remain on
    the HQ catalogue; this endpoint only answers "is this till still safe to
    operate against the current HQ release?".
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.DictField()})
    def get(self, request):
        platform, version, build = client_build_from_request(request)
        if not platform:
            return Response(
                {"detail": "platform is required (query or X-POS-Client-Platform)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resolved = normalize_platform(platform)
        if resolved not in {"WINDOWS", "ANDROID"}:
            return Response(
                {"detail": f"Unsupported platform '{platform}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = evaluate_client_version(
            platform=resolved,
            client_version=version,
            client_build=build,
        )
        return Response(result.as_dict())
