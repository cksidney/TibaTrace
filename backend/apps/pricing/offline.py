"""Signed offline price packages.

A till that has lost its network still has customers. It prices them from a
package issued in advance, and everything here exists because that package is a
file on a device somebody else can reach.

The signing primitives are the repository's existing ones -- domain-separated
HMAC over canonically encoded bytes, compared in constant time. They are not
reimplemented here. This repository has already shipped one forgeable offline
signing scheme, and the lesson taken from that was to have one signing
implementation rather than a second one that looks similar.

Verification fails closed on every uncertain path, and checks in an order chosen
so nothing is trusted before it is authenticated:

    signature, then tenant, then branch, then expiry, then contents.

Checking the branch before the signature would mean reading an attacker's claim
about which branch a package is for and acting on it.

A package is bound to one branch. A price list is not a neutral document: it is
what a specific shop charges, and a package that verifies at any branch lets
whoever holds it price a premium airport till at suburban rates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.cds.offline_package_signing import canonical_bytes, sign_payload, verify_payload

#: Current package format. A package declaring anything else is refused rather
#: than parsed leniently: an unrecognised version means the reader does not know
#: what the fields mean, and guessing at prices is how a till charges the wrong
#: amount with full confidence.
PACKAGE_VERSION = "PRICING_PACKAGE_V1"

#: How long a package may be relied on. Prices change, and a package that never
#: expires is a price list that never updates.
DEFAULT_VALIDITY = timedelta(hours=24)


class Rejection:
    """Why a package was refused. Each is a distinct operational situation."""

    INVALID_SIGNATURE = "PRICE_PACKAGE_INVALID_SIGNATURE"
    UNKNOWN_VERSION = "PRICE_PACKAGE_UNKNOWN_VERSION"
    WRONG_TENANT = "PRICE_PACKAGE_WRONG_TENANT"
    WRONG_BRANCH = "PRICE_PACKAGE_WRONG_BRANCH"
    WRONG_DEVICE = "PRICE_PACKAGE_WRONG_DEVICE"
    EXPIRED = "PRICE_PACKAGE_EXPIRED"
    NOT_YET_VALID = "PRICE_PACKAGE_NOT_YET_VALID"
    MALFORMED = "PRICE_PACKAGE_MALFORMED"


@dataclass(frozen=True)
class PackageVerification:
    """The outcome of checking a package. Never a bare boolean."""

    valid: bool
    code: str = ""
    message: str = ""
    payload: dict[str, Any] | None = None

    @classmethod
    def ok(cls, payload: dict[str, Any]) -> "PackageVerification":
        return cls(valid=True, payload=payload)

    @classmethod
    def refuse(cls, code: str, message: str) -> "PackageVerification":
        # No payload on a refusal. Returning the contents of a package that
        # failed verification invites a caller to use them anyway.
        return cls(valid=False, code=code, message=message, payload=None)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)
    return None


class OfflinePricePackageService:
    """Issues and verifies offline price packages."""

    @staticmethod
    def build(*, tenant_id, branch_id, device_id: str, entries: list[dict],
              promotions: list[dict] | None = None, issued_at: datetime | None = None,
              validity: timedelta | None = None) -> tuple[dict, str]:
        """Issue a package for one branch and one device.

        Returns (payload, signature). The signature covers the whole payload
        including tenant, branch, device and expiry, so none of them can be
        edited without invalidating it -- which is the point of putting them
        inside rather than alongside.
        """
        issued = issued_at or timezone.now()
        payload = {
            "package_version": PACKAGE_VERSION,
            "tenant_id": str(tenant_id),
            "branch_id": str(branch_id),
            "device_id": str(device_id),
            "issued_at": issued.isoformat(),
            "expires_at": (issued + (validity or DEFAULT_VALIDITY)).isoformat(),
            "entries": entries,
            "promotions": promotions or [],
        }
        return payload, sign_payload(payload)

    @staticmethod
    def verify(*, payload: Any, signature: str, expected_tenant_id, expected_branch_id,
               expected_device_id: str | None = None, now: datetime | None = None) -> PackageVerification:
        """Check a package before any of it is believed.

        The order is deliberate. Signature first, because every field after it
        is an attacker-supplied claim until the signature says otherwise.
        """
        now = now or timezone.now()

        if not isinstance(payload, dict) or not payload:
            return PackageVerification.refuse(
                Rejection.MALFORMED, "Price package payload is not an object."
            )

        if not verify_payload(payload, signature):
            return PackageVerification.refuse(
                Rejection.INVALID_SIGNATURE,
                "Price package signature does not verify. The package may have "
                "been altered or issued by something that is not this system.",
            )

        # Everything below is now known to be what was signed.
        version = str(payload.get("package_version") or "")
        if version != PACKAGE_VERSION:
            return PackageVerification.refuse(
                Rejection.UNKNOWN_VERSION,
                f"Unsupported price package version {version or '(none)'}. An "
                "unrecognised version means the fields cannot be read reliably.",
            )

        if str(payload.get("tenant_id") or "") != str(expected_tenant_id):
            return PackageVerification.refuse(
                Rejection.WRONG_TENANT,
                "Price package was issued for another tenant.",
            )

        if str(payload.get("branch_id") or "") != str(expected_branch_id):
            return PackageVerification.refuse(
                Rejection.WRONG_BRANCH,
                "Price package was issued for another branch. A price list is "
                "what a specific shop charges, not a neutral document.",
            )

        if expected_device_id is not None and str(payload.get("device_id") or "") != str(
            expected_device_id
        ):
            return PackageVerification.refuse(
                Rejection.WRONG_DEVICE, "Price package was issued for another device."
            )

        issued = _as_datetime(payload.get("issued_at"))
        expires = _as_datetime(payload.get("expires_at"))
        if expires is None:
            return PackageVerification.refuse(
                Rejection.MALFORMED, "Price package declares no expiry."
            )
        if issued is not None and now < issued:
            return PackageVerification.refuse(
                Rejection.NOT_YET_VALID, "Price package is not yet valid."
            )
        if now >= expires:
            return PackageVerification.refuse(
                Rejection.EXPIRED,
                f"Price package expired at {expires.isoformat()}. Synchronise "
                "before pricing offline.",
            )

        return PackageVerification.ok(payload)

    @classmethod
    def price_from_package(cls, *, payload: dict, sku_id: str, quantity: Decimal = Decimal("1")):
        """Look a price up inside an already-verified package.

        Takes a verified payload rather than a package and signature, so it
        cannot be called on unverified data by accident -- the type of the
        argument is the reminder.

        Returns None when the item is absent. An offline till must refuse to
        sell an item it has no price for rather than invent one, exactly as the
        online engine does.
        """
        best = None
        for entry in payload.get("entries", []):
            if str(entry.get("sku_id")) != str(sku_id):
                continue
            minimum = Decimal(str(entry.get("minimum_quantity", "1")))
            if Decimal(str(quantity)) < minimum:
                continue
            # Highest qualifying band wins, so a wholesale tier beats retail at
            # volume and retail applies below it.
            if best is None or minimum > Decimal(str(best.get("minimum_quantity", "1"))):
                best = entry
        if best is None:
            return None
        return Decimal(str(best["unit_price"]))

    @staticmethod
    def digest(payload: dict) -> str:
        """A stable fingerprint, for logging which package a till was using."""
        import hashlib

        return hashlib.sha256(canonical_bytes(payload)).hexdigest()
