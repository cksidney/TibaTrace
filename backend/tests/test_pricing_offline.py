"""Offline price packages.

A package is a file on a device somebody else can reach. These tests are written
from that assumption: every field in it is an attacker's claim until the
signature says otherwise.

This repository has already shipped one forgeable offline signing scheme. Do not
weaken any of these to make a sync workflow smoother.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.pricing.offline import (
    DEFAULT_VALIDITY,
    PACKAGE_VERSION,
    OfflinePricePackageService,
    Rejection,
)

SIGNING_KEY = "offline-price-package-signing-key-for-tests"
TENANT = "tenant-1"
BRANCH = "branch-eldoret"
DEVICE = "TILL-03"


def cash(value: str) -> Decimal:
    return Decimal(value)


def entries():
    return [
        {"sku_id": "sku-amox", "unit_price": "600.00", "minimum_quantity": "1"},
        {"sku_id": "sku-amox", "unit_price": "450.00", "minimum_quantity": "100"},
        {"sku_id": "sku-para", "unit_price": "120.00", "minimum_quantity": "1"},
    ]


def issue(**overrides):
    kwargs = {
        "tenant_id": TENANT,
        "branch_id": BRANCH,
        "device_id": DEVICE,
        "entries": entries(),
    }
    kwargs.update(overrides)
    return OfflinePricePackageService.build(**kwargs)


def verify(payload, signature, **overrides):
    kwargs = {
        "payload": payload,
        "signature": signature,
        "expected_tenant_id": TENANT,
        "expected_branch_id": BRANCH,
    }
    kwargs.update(overrides)
    return OfflinePricePackageService.verify(**kwargs)


@pytest.fixture(autouse=True)
def signing_key(settings):
    """Every test in this module signs and verifies with the same key.

    Set through the settings fixture rather than a module-level mark, because
    override_settings is a decorator and a context manager, not a pytest mark.
    """
    settings.DAWATRACE_OBJECT_SIGNING_KEY = SIGNING_KEY


# ─── a genuine package works ─────────────────────────────────────────────────


class TestIssuance:
    def test_a_freshly_issued_package_verifies(self):
        payload, signature = issue()
        assert verify(payload, signature).valid is True

    def test_the_package_declares_its_version(self):
        payload, _ = issue()
        assert payload["package_version"] == PACKAGE_VERSION

    def test_the_validity_window_is_bounded(self):
        # A package that never expires is a price list that never updates.
        assert DEFAULT_VALIDITY <= timedelta(days=7)

    def test_tenant_branch_and_device_are_inside_the_signature(self):
        """Not alongside it.

        Fields outside the signed payload can be edited without breaking the
        signature, which is the whole attack.
        """
        payload, _ = issue()
        for field in ("tenant_id", "branch_id", "device_id", "expires_at"):
            assert field in payload


# ─── forgery and tampering ───────────────────────────────────────────────────


class TestSignature:
    def test_a_forged_signature_is_refused(self):
        payload, _ = issue()
        result = verify(payload, "0" * 64)
        assert result.valid is False
        assert result.code == Rejection.INVALID_SIGNATURE

    def test_an_empty_signature_is_refused(self):
        payload, _ = issue()
        assert verify(payload, "").code == Rejection.INVALID_SIGNATURE

    def test_an_edited_price_invalidates_the_signature(self):
        """The attack the signature exists to stop."""
        payload, signature = issue()
        payload["entries"][0]["unit_price"] = "1.00"
        assert verify(payload, signature).code == Rejection.INVALID_SIGNATURE

    def test_an_edited_branch_invalidates_the_signature(self):
        payload, signature = issue()
        payload["branch_id"] = "branch-mombasa"
        assert verify(payload, signature).code == Rejection.INVALID_SIGNATURE

    def test_an_extended_expiry_invalidates_the_signature(self):
        # Otherwise an expired package is revived by editing one field.
        payload, signature = issue()
        payload["expires_at"] = (timezone.now() + timedelta(days=365)).isoformat()
        assert verify(payload, signature).code == Rejection.INVALID_SIGNATURE

    def test_an_added_entry_invalidates_the_signature(self):
        payload, signature = issue()
        payload["entries"].append(
            {"sku_id": "sku-gold", "unit_price": "0.01", "minimum_quantity": "1"}
        )
        assert verify(payload, signature).code == Rejection.INVALID_SIGNATURE

    def test_a_package_signed_with_another_key_is_refused(self):
        with override_settings(DAWATRACE_OBJECT_SIGNING_KEY="somebody-elses-key"):
            payload, signature = issue()
        # Signed elsewhere, presented here.
        assert verify(payload, signature).code == Rejection.INVALID_SIGNATURE


# ─── the package is bound to one place ───────────────────────────────────────


class TestBinding:
    def test_another_branchs_package_is_refused(self):
        """A price list is what a specific shop charges.

        A package that verified anywhere would let whoever holds it price a
        premium airport till at suburban rates.
        """
        payload, signature = issue(branch_id="branch-mombasa")
        result = verify(payload, signature)
        assert result.valid is False
        assert result.code == Rejection.WRONG_BRANCH

    def test_another_tenants_package_is_refused(self):
        payload, signature = issue(tenant_id="tenant-2")
        assert verify(payload, signature).code == Rejection.WRONG_TENANT

    def test_another_devices_package_is_refused_when_a_device_is_expected(self):
        payload, signature = issue(device_id="TILL-99")
        result = verify(payload, signature, expected_device_id=DEVICE)
        assert result.code == Rejection.WRONG_DEVICE

    def test_the_device_check_is_optional(self):
        # Some deployments issue per branch rather than per till.
        payload, signature = issue(device_id="TILL-99")
        assert verify(payload, signature).valid is True


# ─── time ────────────────────────────────────────────────────────────────────


class TestExpiry:
    def test_an_expired_package_is_refused(self):
        issued = timezone.now() - timedelta(days=3)
        payload, signature = issue(issued_at=issued, validity=timedelta(hours=1))
        result = verify(payload, signature)
        assert result.valid is False
        assert result.code == Rejection.EXPIRED

    def test_a_package_from_the_future_is_refused(self):
        issued = timezone.now() + timedelta(hours=2)
        payload, signature = issue(issued_at=issued)
        assert verify(payload, signature).code == Rejection.NOT_YET_VALID

    def test_a_package_is_valid_up_to_its_expiry(self):
        issued = timezone.now() - timedelta(hours=1)
        payload, signature = issue(issued_at=issued, validity=timedelta(hours=2))
        assert verify(payload, signature).valid is True


# ─── version handling ────────────────────────────────────────────────────────


class TestVersion:
    def test_an_unknown_version_is_refused_rather_than_parsed(self):
        """Guessing at prices is how a till charges the wrong amount with full
        confidence."""
        payload, _ = issue()
        payload["package_version"] = "PRICING_PACKAGE_V99"
        from apps.cds.offline_package_signing import sign_payload

        # Correctly signed, but a version this reader does not understand.
        assert verify(payload, sign_payload(payload)).code == Rejection.UNKNOWN_VERSION

    def test_a_missing_version_is_refused(self):
        payload, _ = issue()
        del payload["package_version"]
        from apps.cds.offline_package_signing import sign_payload

        assert verify(payload, sign_payload(payload)).code == Rejection.UNKNOWN_VERSION


# ─── refusals carry nothing usable ───────────────────────────────────────────


class TestFailClosed:
    def test_a_refusal_returns_no_payload(self):
        """Returning the contents of a package that failed verification invites
        a caller to use them anyway."""
        payload, _ = issue()
        result = verify(payload, "0" * 64)
        assert result.payload is None

    def test_a_malformed_payload_is_refused(self):
        assert OfflinePricePackageService.verify(
            payload="not a dict", signature="x",
            expected_tenant_id=TENANT, expected_branch_id=BRANCH,
        ).code == Rejection.MALFORMED

    def test_an_empty_payload_is_refused(self):
        assert OfflinePricePackageService.verify(
            payload={}, signature="x",
            expected_tenant_id=TENANT, expected_branch_id=BRANCH,
        ).code == Rejection.MALFORMED

    def test_the_signature_is_checked_before_the_branch(self):
        """Order matters.

        Checking the branch first would mean reading an attacker's claim about
        which branch a package is for and acting on it.
        """
        payload, _ = issue(branch_id="branch-mombasa")
        result = verify(payload, "0" * 64)
        # Reported as a bad signature, not as a wrong branch.
        assert result.code == Rejection.INVALID_SIGNATURE


# ─── pricing from a verified package ─────────────────────────────────────────


class TestOfflinePricing:
    def test_a_price_is_found(self):
        payload, signature = issue()
        verified = verify(payload, signature)
        price = OfflinePricePackageService.price_from_package(
            payload=verified.payload, sku_id="sku-amox"
        )
        assert price == cash("600.00")

    def test_a_quantity_band_applies_at_volume(self):
        payload, signature = issue()
        verified = verify(payload, signature)
        price = OfflinePricePackageService.price_from_package(
            payload=verified.payload, sku_id="sku-amox", quantity=Decimal("100")
        )
        assert price == cash("450.00")

    def test_an_absent_item_has_no_price(self):
        """An offline till refuses to sell what it has no price for, exactly as
        the online engine does. Inventing one is worse than refusing."""
        payload, signature = issue()
        verified = verify(payload, signature)
        assert OfflinePricePackageService.price_from_package(
            payload=verified.payload, sku_id="sku-unknown"
        ) is None

    def test_pricing_takes_a_verified_payload_not_a_package(self):
        # The argument type is the reminder that verification comes first.
        import inspect

        signature = inspect.signature(OfflinePricePackageService.price_from_package)
        assert "payload" in signature.parameters
        assert "signature" not in signature.parameters


class TestDigest:
    def test_the_digest_is_stable(self):
        payload, _ = issue()
        assert OfflinePricePackageService.digest(payload) == (
            OfflinePricePackageService.digest(payload)
        )

    def test_the_digest_changes_with_content(self):
        payload, _ = issue()
        first = OfflinePricePackageService.digest(payload)
        payload["entries"][0]["unit_price"] = "601.00"
        assert OfflinePricePackageService.digest(payload) != first


class TestSigningReuse:
    def test_the_module_does_not_reimplement_signing(self):
        """One signing implementation, not a second that looks similar.

        This repository has already shipped one forgeable offline scheme.
        """
        from apps.pricing import offline

        source = open(offline.__file__).read()
        assert "from apps.cds.offline_package_signing import" in source
        for reimplementation in ("hmac.new(", "hashlib.sha256(canonical", "compare_digest"):
            assert reimplementation not in source.split("def digest")[0]
