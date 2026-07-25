"""Signing and verification for offline clinical packages.

An offline package tells a POS terminal which clinical rules apply when it
cannot reach the server. If it can be forged, offline dispensing safety can be
switched off by anyone who can write a file to the device -- so the signature is
the whole security boundary.

The original scheme keyed the HMAC on ``tenant.pk``. A tenant UUID is public
metadata: it appears in API responses, URLs and logs. That made every signature
forgeable by anyone holding an ID they were already given. This module replaces
it with the repository's configured signing secret and binds the full context
into the signed payload.

Follows the convention in ``apps/prescription/security/digital_signatures.py``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

from django.conf import settings

#: Domain separation. Prevents a signature produced for some other object type
#: under the same key from ever being replayed as an offline package.
SIGNING_DOMAIN = "dawatrace.offline_clinical_package.v1"

ALGORITHM = "HS256"

#: A package issued more than this far in the future is rejected. Guards against
#: a tampered or badly-clocked issuer minting a long-lived package.
FUTURE_ISSUE_TOLERANCE_SECONDS = 300


class SigningKeyUnavailable(RuntimeError):
    """Raised when no signing key is configured.

    Deliberately an error rather than a falsy return: a missing key must never
    be mistaken for a failed comparison, and must never permit a package.
    """


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    code: str
    message: str = ""
    package_id: str = ""
    signing_version: str = ""
    issued_at: str = ""
    expires_at: str = ""
    context_hash: str = ""
    permitted_actions: list[str] = field(default_factory=list)

    @classmethod
    def failure(cls, code: str, message: str = "", **extra) -> "VerificationResult":
        return cls(valid=False, code=code, message=message or code, **extra)


def _signing_key() -> bytes:
    key = str(getattr(settings, "DAWATRACE_OBJECT_SIGNING_KEY", "") or "")
    if not key:
        raise SigningKeyUnavailable(
            "DAWATRACE_OBJECT_SIGNING_KEY is required to sign or verify offline "
            "clinical packages."
        )
    return key.encode("utf-8")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic encoding of the payload.

    Signing non-deterministically serialised JSON is a real hazard: two encoders
    that order keys differently produce different signatures over identical
    data, which shows up as spurious verification failures and tempts people to
    weaken the check. Sorted keys, no insignificant whitespace, UTF-8, and no
    non-ASCII escaping ambiguity.
    """
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return f"{SIGNING_DOMAIN}\n{encoded}".encode("utf-8")


def sign_payload(payload: dict[str, Any]) -> str:
    return hmac.new(_signing_key(), canonical_bytes(payload), hashlib.sha256).hexdigest()


def verify_payload(payload: dict[str, Any], signature: str) -> bool:
    expected = sign_payload(payload)
    # Constant-time: a byte-by-byte early exit would leak the correct prefix.
    return hmac.compare_digest(expected, str(signature or ""))


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


def build_payload(
    *,
    package_id,
    signing_version: str,
    tenant_id,
    branch_id,
    device_id: str,
    patient_ref: str,
    prescription_ref: str,
    episode_ref: str,
    screening_ref: str,
    context_hash: str,
    findings: list[dict[str, Any]] | None,
    permitted_actions: list[str],
    issued_at: datetime,
    expires_at: datetime,
    package_version: str,
    nonce,
) -> dict[str, Any]:
    """Assemble the canonical payload that gets signed.

    Every field here is security-relevant: anything left outside the signature
    could be altered on a device without invalidating it. Findings are reduced
    to a hash so the signature covers them without the payload carrying more
    clinical detail than it needs to.
    """
    findings_digest = hashlib.sha256(
        json.dumps(findings or [], sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()

    return {
        "package_id": str(package_id),
        "signing_version": signing_version,
        "tenant_id": str(tenant_id),
        "branch_id": str(branch_id) if branch_id else "",
        "device_id": device_id or "",
        "patient_ref": patient_ref or "",
        "prescription_ref": prescription_ref or "",
        "episode_ref": episode_ref or "",
        "screening_ref": screening_ref or "",
        "context_hash": context_hash or "",
        "findings_digest": findings_digest,
        "permitted_actions": sorted(permitted_actions or []),
        "issued_at": issued_at.astimezone(dt_timezone.utc).isoformat(),
        "expires_at": expires_at.astimezone(dt_timezone.utc).isoformat(),
        "package_version": package_version,
        "nonce": str(nonce),
    }


def verify_package_payload(
    *,
    payload: dict[str, Any],
    signature: str,
    signing_version: str,
    now: datetime,
    expected_tenant_id=None,
    expected_branch_id=None,
    expected_device_id: str | None = None,
    expected_context_hash: str | None = None,
) -> VerificationResult:
    """Authoritative verification. Fails closed on every uncertain path."""
    from apps.cds.pos_screening_models import PosOfflineClinicalPackage

    version = str(signing_version or "")
    if not version:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_UNKNOWN_SIGNING_VERSION",
            "Package does not declare a signing version.",
        )
    if version == PosOfflineClinicalPackage.SigningVersion.LEGACY_TENANT_UUID_HMAC:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_LEGACY_SIGNATURE",
            "Package was signed with the withdrawn tenant-UUID scheme and cannot "
            "be trusted.",
        )
    if version not in PosOfflineClinicalPackage.SUPPORTED_SIGNING_VERSIONS:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_UNKNOWN_SIGNING_VERSION",
            f"Unsupported signing version {version}.",
        )

    if not isinstance(payload, dict) or not payload:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_INVALID_SIGNATURE", "Package payload is missing or malformed."
        )

    # A payload whose declared version disagrees with the record is tampered.
    if str(payload.get("signing_version") or "") != version:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_INVALID_SIGNATURE",
            "Signing version does not match the signed payload.",
        )

    try:
        signature_ok = verify_payload(payload, signature)
    except SigningKeyUnavailable as exc:
        # Misconfiguration must not read as a valid package.
        return VerificationResult.failure("OFFLINE_PACKAGE_INVALID_SIGNATURE", str(exc))
    if not signature_ok:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_INVALID_SIGNATURE", "Signature does not match the payload."
        )

    issued_at = _parse_timestamp(payload.get("issued_at"))
    expires_at = _parse_timestamp(payload.get("expires_at"))
    if issued_at is None or expires_at is None:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_INVALID_SIGNATURE", "Package timestamps are missing or malformed."
        )

    common = {
        "package_id": str(payload.get("package_id") or ""),
        "signing_version": version,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "context_hash": str(payload.get("context_hash") or ""),
        "permitted_actions": list(payload.get("permitted_actions") or []),
    }

    if expires_at <= now:
        return VerificationResult.failure("OFFLINE_PACKAGE_EXPIRED", "Package has expired.", **common)
    if (issued_at - now).total_seconds() > FUTURE_ISSUE_TOLERANCE_SECONDS:
        return VerificationResult.failure(
            "OFFLINE_PACKAGE_NOT_YET_VALID", "Package issue time is in the future.", **common
        )

    checks = (
        (expected_tenant_id, "tenant_id", "OFFLINE_PACKAGE_WRONG_TENANT"),
        (expected_branch_id, "branch_id", "OFFLINE_PACKAGE_WRONG_BRANCH"),
        (expected_device_id, "device_id", "OFFLINE_PACKAGE_WRONG_DEVICE"),
        (expected_context_hash, "context_hash", "OFFLINE_PACKAGE_STALE_CONTEXT"),
    )
    for expected, key, code in checks:
        if expected is None:
            continue
        if str(payload.get(key) or "") != str(expected):
            return VerificationResult.failure(code, f"Package {key} does not match.", **common)

    return VerificationResult(valid=True, code="OK", message="Package verified", **common)
