"""Where POS installers live, and how a link to one is handed out.

One seam, with one implementation. MinIO speaks the S3 API, so self-hosting and
AWS differ by an endpoint URL in deployment config rather than by any code here.

The artefact is never streamed through the application server. A 35 MB installer
served by Django would occupy a worker for the length of the download, and a
pharmacy on a slow connection would occupy it for minutes. The server issues a
signed URL and the client fetches from storage directly.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

#: How long a download link stays valid.
#:
#: Long enough to start a download on a poor connection, short enough that a
#: link pasted into a group chat stops working. The signature covers the object
#: key, so it grants one file, not the bucket.
DOWNLOAD_URL_TTL_SECONDS = 300


class ReleaseStorageNotConfigured(ImproperlyConfigured):
    """Raised when a download is requested before storage is set up.

    Its own class so the API can answer 503 rather than 500: the request was
    valid and the deployment is incomplete, which is an operator's problem to
    fix and not a caller's to retry differently.
    """


def _config() -> dict:
    required = ("bucket", "endpoint_url", "access_key", "secret_key", "region")
    config = getattr(settings, "POS_RELEASE_STORAGE", {}) or {}
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ReleaseStorageNotConfigured(
            "POS release storage is not configured. Missing: " + ", ".join(missing)
        )
    return config


def signed_download_url(object_key: str, *, filename: str) -> str:
    """A short-lived URL for one object.

    `filename` sets the download name, so a browser saves
    `TibaTrace-POS-0.1.0.msix` rather than the storage key.
    """
    import boto3
    from botocore.config import Config

    config = _config()
    client = boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
        # SigV4 is required by MinIO and by S3 in newer regions.
        config=Config(signature_version="s3v4"),
    )
    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": config["bucket"],
            "Key": object_key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )


def is_configured() -> bool:
    """Whether a download could be issued right now.

    Used to tell an operator that the catalogue is listable but downloads are
    not yet available, instead of letting them click and get an error.
    """
    try:
        _config()
    except ReleaseStorageNotConfigured:
        return False
    return True
