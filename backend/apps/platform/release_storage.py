"""Where POS installers live, and how a link to one is handed out.

Two backends:

* ``s3`` — MinIO or AWS. The application never streams the artefact; it issues
  a short-lived signed URL and the client fetches from storage.
* ``local`` — filesystem under ``MEDIA_ROOT/pos-releases``. Used for
  development and single-node deployments where object storage is not yet
  provisioned. The download URL points back at the HQ API, which streams the
  file for an authenticated session.

Unset S3 credentials no longer disable downloads when the local backend is
active: operators can fetch the seeded Windows and Android kits immediately.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

#: How long a signed object-storage download link stays valid.
DOWNLOAD_URL_TTL_SECONDS = 300

#: How long a local artefact download URL stays valid. Same order of magnitude
#: as the S3 TTL so the UI can keep one "expires in" figure.
LOCAL_DOWNLOAD_URL_TTL_SECONDS = 300


class ReleaseStorageNotConfigured(ImproperlyConfigured):
    """Raised when a download is requested before storage is set up.

    Its own class so the API can answer 503 rather than 500: the request was
    valid and the deployment is incomplete, which is an operator's problem to
    fix and not a caller's to retry differently.
    """


def storage_backend() -> str:
    config = getattr(settings, "POS_RELEASE_STORAGE", {}) or {}
    backend = str(config.get("backend") or "").strip().lower()
    if backend in {"local", "s3"}:
        return backend
    # Prefer S3 when its credentials are present; otherwise fall back to local
    # so a fresh checkout can still serve the seeded installers.
    required = ("bucket", "endpoint_url", "access_key", "secret_key")
    if all(config.get(key) for key in required):
        return "s3"
    return "local"


def local_root() -> Path:
    config = getattr(settings, "POS_RELEASE_STORAGE", {}) or {}
    configured = config.get("local_root")
    if configured:
        return Path(configured)
    return Path(settings.MEDIA_ROOT) / "pos-releases"


def local_object_path(object_key: str) -> Path:
    root = local_root().resolve()
    candidate = (root / object_key).resolve()
    if root not in candidate.parents and candidate != root:
        raise ReleaseStorageNotConfigured("Release object key escapes the storage root.")
    return candidate


def _s3_config() -> dict:
    required = ("bucket", "endpoint_url", "access_key", "secret_key", "region")
    config = getattr(settings, "POS_RELEASE_STORAGE", {}) or {}
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ReleaseStorageNotConfigured(
            "POS release storage is not configured. Missing: " + ", ".join(missing)
        )
    return config


def signed_download_url(object_key: str, *, filename: str) -> str:
    """A short-lived URL for one object on S3-compatible storage.

    `filename` sets the download name, so a browser saves
    `TibaTrace-POS-0.1.0.msix` rather than the storage key.
    """
    import boto3
    from botocore.config import Config

    config = _s3_config()
    client = boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
        # SigV4 is required by MinIO and by S3 in newer regions.
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
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
    backend = storage_backend()
    if backend == "local":
        return True
    try:
        _s3_config()
    except ReleaseStorageNotConfigured:
        return False
    return True


def ensure_local_artifact(object_key: str, content: bytes) -> Path:
    """Write an installer into the local release root and return its path."""
    path = local_object_path(object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
