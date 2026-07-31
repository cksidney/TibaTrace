"""POS installer distribution.

Both endpoints require an authenticated HQ session. An installer is not secret,
but an unauthenticated download endpoint is an open file host on the pharmacy's
own domain, and there is no reason to run one.

Downloads are audited. Knowing which build a till is running is the first
question asked when a counter misbehaves, and the answer is only available if
the fetch was recorded.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.models import PosRelease
from apps.platform.release_storage import (
    DOWNLOAD_URL_TTL_SECONDS,
    LOCAL_DOWNLOAD_URL_TTL_SECONDS,
    ReleaseStorageNotConfigured,
    is_configured,
    local_object_path,
    signed_download_url,
    storage_backend,
)

#: What a saved file is called. The storage key is an implementation detail and
#: makes a poor filename in a downloads folder.
DEFAULT_FILENAME_SUFFIX = {
    PosRelease.Platform.WINDOWS: "msix",
    PosRelease.Platform.ANDROID: "apk",
}
SUPPORTED_FILENAME_SUFFIXES = frozenset({"apk", "exe", "msix", "zip"})


def download_filename(release: PosRelease) -> str:
    suffix = PurePosixPath(release.object_key).suffix.removeprefix(".").lower()
    if suffix not in SUPPORTED_FILENAME_SUFFIXES:
        suffix = DEFAULT_FILENAME_SUFFIX.get(release.platform, "bin")
    platform = release.platform.lower()
    return f"TibaTrace-POS-{platform}-{release.version}.{suffix}"


class PosReleaseSerializer(serializers.ModelSerializer):
    download_filename = serializers.SerializerMethodField()

    class Meta:
        model = PosRelease
        fields = (
            "id",
            "platform",
            "version",
            "build_number",
            "size_bytes",
            "sha256",
            "release_notes",
            "minimum_os",
            "minimum_supported_build",
            "operations_impact",
            "published_at",
            "download_filename",
        )

    def get_download_filename(self, release) -> str:
        return download_filename(release)


class PosReleaseListView(APIView):
    """Published installers, newest build first.

    Unpublished rows are never listed: uploading an artefact and releasing it
    are separate acts, so an upload in progress cannot be downloaded by someone
    watching the page.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=PosReleaseSerializer(many=True))
    def get(self, request):
        releases = PosRelease.objects.filter(is_published=True).order_by(
            "platform", "-build_number"
        )
        return Response(
            {
                "downloads_available": is_configured(),
                "url_ttl_seconds": (
                    LOCAL_DOWNLOAD_URL_TTL_SECONDS
                    if storage_backend() == "local"
                    else DOWNLOAD_URL_TTL_SECONDS
                ),
                "storage_backend": storage_backend(),
                "releases": PosReleaseSerializer(releases, many=True).data,
            }
        )


class PosReleaseDownloadView(APIView):
    """Issue a short-lived URL for one installer.

    The response is the URL rather than a redirect, so the client can show the
    checksum next to the link and the operator can verify what they downloaded.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.DictField()})
    def post(self, request, pk):
        release = PosRelease.objects.filter(pk=pk, is_published=True).first()
        if release is None:
            # Unpublished and absent are the same answer. Otherwise this
            # endpoint reports which builds exist but are not yet released.
            return Response(
                {"detail": "Release not found."}, status=status.HTTP_404_NOT_FOUND
            )

        filename = download_filename(release)
        try:
            if storage_backend() == "local":
                path = local_object_path(release.object_key)
                if not path.is_file():
                    raise ReleaseStorageNotConfigured(
                        f"Local installer is missing at {release.object_key}."
                    )
                url = request.build_absolute_uri(
                    f"/api/hq/pos-releases/{release.pk}/artifact/"
                )
                expires = LOCAL_DOWNLOAD_URL_TTL_SECONDS
            else:
                url = signed_download_url(release.object_key, filename=filename)
                expires = DOWNLOAD_URL_TTL_SECONDS
        except ReleaseStorageNotConfigured as exc:
            # 503, not 500: the request was valid and the deployment is
            # incomplete. Retrying the same request will not help.
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        from apps.audit.models import AuditEvent

        if tenant_id := getattr(request.user, "tenant_id", None):
            AuditEvent.all_objects.create(
                tenant_id=tenant_id,
                actor=request.user,
                action="POS_RELEASE_DOWNLOADED",
                model_name="PosRelease",
                object_id=str(release.pk),
                outcome="SUCCESS",
                metadata={
                    "platform": release.platform,
                    "version": release.version,
                    "sha256": release.sha256,
                },
            )

        return Response(
            {
                "url": url,
                "filename": filename,
                "expires_in_seconds": expires,
                "sha256": release.sha256,
                "size_bytes": release.size_bytes,
            }
        )


class PosReleaseArtifactView(APIView):
    """Stream a local installer for an authenticated HQ session.

    Used when object storage is not configured. Session cookies travel with the
    browser navigation that follows the download URL, so this stays behind the
    same authentication gate as the catalogue.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if storage_backend() != "local":
            return Response(
                {"detail": "Local artefact streaming is only available for the local backend."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        release = PosRelease.objects.filter(pk=pk, is_published=True).first()
        if release is None:
            return Response({"detail": "Release not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            path = local_object_path(release.object_key)
        except ReleaseStorageNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not path.is_file():
            return Response(
                {"detail": "Installer artefact is missing from local storage."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        filename = download_filename(release)
        response = FileResponse(path.open("rb"), as_attachment=True, filename=filename)
        response["Content-Length"] = str(path.stat().st_size)
        return response
