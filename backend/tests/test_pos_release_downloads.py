"""Distributing POS installers from HQ.

Two endpoints: a list of published builds, and one that issues a short-lived
signed URL for a single build. Both require an authenticated HQ session -- an
installer is not secret, but an unauthenticated download endpoint is an open
file host on the pharmacy's own domain.

The artefact never passes through the application server. A 35 MB installer
streamed by Django would hold a worker for the length of the download, so the
server signs a URL and the client fetches from storage directly.
"""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.platform.models import PosRelease
from apps.tenancy.models import Tenant

PASSWORD = "release-password-long-enough"
DIGEST = "b" * 64

STORAGE = {
    "bucket": "tibatrace-releases",
    "endpoint_url": "https://minio.example.test",
    "access_key": "key",
    "secret_key": "secret",
    "region": "us-east-1",
}


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    tenant = Tenant.objects.create(name="Rel Tenant", slug="rel-tenant")
    return User.objects.create_user(
        username="rel-user", password=PASSWORD, tenant=tenant
    )


@pytest.fixture
def published(db):
    return PosRelease.objects.create(
        platform=PosRelease.Platform.ANDROID, version="0.1.0-alpha.1",
        build_number=1, object_key="android/0.1.0-alpha.1/pos.apk",
        size_bytes=36_700_160, sha256=DIGEST, minimum_os="Android 10",
        release_notes="First counter build.", is_published=True,
    )


@pytest.fixture
def unpublished(db):
    return PosRelease.objects.create(
        platform=PosRelease.Platform.WINDOWS, version="0.2.0",
        build_number=2, object_key="windows/0.2.0/pos.msix",
        size_bytes=51_200_000, sha256="c" * 64, is_published=False,
    )


def signed_in(user):
    client = APIClient()
    response = client.post(
        "/api/identity/session/",
        {"username": user.username, "password": PASSWORD}, format="json",
    )
    assert response.status_code == 200, response.content
    return client


# ─── the session requirement ─────────────────────────────────────────────────


class TestAuthenticationIsRequired:
    def test_an_anonymous_caller_cannot_list_releases(self, published):
        response = APIClient().get("/api/hq/pos-releases/")
        assert response.status_code in (401, 403)

    def test_an_anonymous_caller_cannot_request_a_download(self, published):
        response = APIClient().post(f"/api/hq/pos-releases/{published.pk}/download/")
        assert response.status_code in (401, 403)
        # And no URL leaks in the refusal.
        assert "http" not in response.content.decode().replace("https://", "")

    def test_a_signed_in_operator_can_list(self, user, published):
        response = signed_in(user).get("/api/hq/pos-releases/")
        assert response.status_code == 200
        assert len(response.json()["releases"]) == 1


# ─── what is listed ──────────────────────────────────────────────────────────


class TestListing:
    def test_an_unpublished_build_is_not_listed(self, user, published, unpublished):
        """Uploading and releasing are separate acts.

        An upload in progress must not be downloadable by somebody refreshing
        the page.
        """
        versions = {
            r["version"] for r in signed_in(user).get("/api/hq/pos-releases/").json()["releases"]
        }
        assert versions == {"0.1.0-alpha.1"}

    def test_the_checksum_and_size_are_published_with_the_build(self, user, published):
        row = signed_in(user).get("/api/hq/pos-releases/").json()["releases"][0]
        assert row["sha256"] == DIGEST
        assert row["size_bytes"] == 36_700_160
        # So an operator knows before downloading whether the till can run it.
        assert row["minimum_os"] == "Android 10"

    def test_the_filename_is_meaningful_rather_than_the_storage_key(self, user, published):
        row = signed_in(user).get("/api/hq/pos-releases/").json()["releases"][0]
        assert row["download_filename"] == "TibaTrace-POS-android-0.1.0-alpha.1.apk"

    def test_the_list_says_whether_downloads_are_available(self, user, published):
        # Unconfigured storage is reported up front rather than discovered by
        # clicking a link that fails.
        body = signed_in(user).get("/api/hq/pos-releases/").json()
        assert body["downloads_available"] is False


# ─── issuing a link ──────────────────────────────────────────────────────────


class TestDownload:
    def test_a_signed_url_is_issued_for_a_published_build(self, user, published):
        with patch(
            "apps.platform.release_views.signed_download_url",
            return_value="https://minio.example.test/signed",
        ) as signer:
            response = signed_in(user).post(
                f"/api/hq/pos-releases/{published.pk}/download/"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["url"] == "https://minio.example.test/signed"
        assert body["sha256"] == DIGEST
        assert body["expires_in_seconds"] > 0
        # Signed for the stored key, with the friendly filename attached.
        signer.assert_called_once()
        assert signer.call_args.args[0] == "android/0.1.0-alpha.1/pos.apk"

    def test_an_unpublished_build_is_not_downloadable(self, user, unpublished):
        response = signed_in(user).post(
            f"/api/hq/pos-releases/{unpublished.pk}/download/"
        )
        # 404 rather than 403: otherwise the endpoint reports which builds exist
        # but have not been released.
        assert response.status_code == 404

    def test_unconfigured_storage_answers_503_not_500(self, user, published):
        """The request was valid; the deployment is incomplete.

        A 500 would send somebody looking for a bug in the request.
        """
        response = signed_in(user).post(f"/api/hq/pos-releases/{published.pk}/download/")
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_a_download_is_audited(self, user, published):
        from apps.audit.models import AuditEvent

        with patch(
            "apps.platform.release_views.signed_download_url",
            return_value="https://minio.example.test/signed",
        ):
            signed_in(user).post(f"/api/hq/pos-releases/{published.pk}/download/")

        event = AuditEvent.all_objects.filter(action="POS_RELEASE_DOWNLOADED").first()
        assert event is not None, (
            "Which build a till is running is the first question asked when a "
            "counter misbehaves, and it is only answerable if the fetch was "
            "recorded."
        )
        assert event.object_id == str(published.pk)
        assert event.metadata["version"] == "0.1.0-alpha.1"


# ─── the row itself ──────────────────────────────────────────────────────────


class TestReleaseValidation:
    def test_a_malformed_checksum_is_refused(self, db):
        from django.core.exceptions import ValidationError

        release = PosRelease(
            platform=PosRelease.Platform.ANDROID, version="9.9.9", build_number=99,
            object_key="a/b.apk", size_bytes=1, sha256="not-a-digest",
        )
        # A wrong checksum is worse than none: it invites an operator to
        # "verify" and pass.
        with pytest.raises(ValidationError, match="SHA-256"):
            release.full_clean()

    def test_a_zero_byte_installer_is_refused(self, db):
        from django.core.exceptions import ValidationError

        release = PosRelease(
            platform=PosRelease.Platform.ANDROID, version="9.9.8", build_number=98,
            object_key="a/b.apk", size_bytes=0, sha256=DIGEST,
        )
        with pytest.raises(ValidationError, match="zero bytes"):
            release.full_clean()

    def test_the_checksum_is_stored_lowercase(self, db):
        release = PosRelease.objects.create(
            platform=PosRelease.Platform.WINDOWS, version="9.9.7", build_number=97,
            object_key="a/b.msix", size_bytes=10, sha256=DIGEST.upper(),
        )
        # So a comparison against `sha256sum` output never fails on case.
        release.refresh_from_db()
        assert release.sha256 == DIGEST


class TestStorageConfiguration:
    def test_a_signed_url_is_requested_with_the_configured_endpoint(self, settings):
        """MinIO and S3 differ by this value and nothing else."""
        settings.POS_RELEASE_STORAGE = STORAGE
        from apps.platform import release_storage

        with patch("boto3.client") as client:
            client.return_value.generate_presigned_url.return_value = "https://signed"
            url = release_storage.signed_download_url("k/v.apk", filename="v.apk")

        assert url == "https://signed"
        assert client.call_args.kwargs["endpoint_url"] == "https://minio.example.test"
        assert client.call_args.kwargs["config"].s3 == {"addressing_style": "path"}
        params = client.return_value.generate_presigned_url.call_args.kwargs["Params"]
        assert params["Bucket"] == "tibatrace-releases"
        assert params["Key"] == "k/v.apk"
        assert 'filename="v.apk"' in params["ResponseContentDisposition"]
