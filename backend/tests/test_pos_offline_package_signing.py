"""Offline clinical package signing, expiry and revocation.

These are audit-evidence tests. Each corresponds to a defect present in the
implementation shipped by b3d950e, where the HMAC key was ``tenant.pk``.

A tenant UUID is public metadata -- it appears in API responses, URLs and logs
-- so under the old scheme anyone holding a tenant ID could mint a package that
verified, including one with every blocking clinical rule switched off. An
offline package tells a POS terminal which clinical rules apply when it cannot
reach the server, so that signature is the entire security boundary.

Do not relax these tests to make a future change easier.
"""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.cds.offline_package_signing import (
    FUTURE_ISSUE_TOLERANCE_SECONDS,
    SIGNING_DOMAIN,
    canonical_bytes,
)
from apps.cds.pos_screening_models import PosOfflineClinicalPackage
from apps.cds.pos_screening_services import PosOfflinePackageService
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db

V1 = PosOfflineClinicalPackage.SigningVersion.OBJECT_SIGNING_KEY_V1
LEGACY = PosOfflineClinicalPackage.SigningVersion.LEGACY_TENANT_UUID_HMAC


@pytest.fixture
def tenant():
    return Tenant.objects.create(name="Signing Co", slug="signing-co")


@pytest.fixture
def package(tenant):
    return PosOfflinePackageService.generate_package(
        tenant=tenant, device_id="TILL-1", context_hash="ctx-abc"
    )


def verify(tenant, pkg, **overrides):
    kwargs = {
        "tenant": tenant,
        "package_data": pkg.package_data,
        "signature": pkg.signature,
        "signing_version": pkg.signing_version,
    }
    kwargs.update(overrides)
    return PosOfflinePackageService.verify(**kwargs)


def legacy_signature(tenant_pk, payload):
    """Reproduce the withdrawn scheme exactly."""
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hmac.new(
        str(tenant_pk).encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# --------------------------------------------------------------- the defect


def test_tenant_uuid_can_no_longer_forge_a_package(tenant, package):
    """The original attack, executed against the current implementation.

    Previously both a genuine and a tampered package verified using nothing but
    the tenant UUID.
    """
    forged = dict(package.package_data)
    forged["permitted_actions"] = ["DISPENSE_CONTROLLED"]
    signature = legacy_signature(tenant.pk, forged)

    assert verify(tenant, package, package_data=forged, signature=signature,
                  signing_version=LEGACY).valid is False
    # ...and it cannot be laundered by relabelling it as the current version.
    assert verify(tenant, package, package_data=forged, signature=signature,
                  signing_version=V1).valid is False


def test_legacy_signing_version_is_rejected_outright(tenant, package):
    result = verify(tenant, package, signing_version=LEGACY)
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_LEGACY_SIGNATURE"


def test_missing_signing_version_is_not_treated_as_current(tenant, package):
    result = verify(tenant, package, signing_version="")
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_UNKNOWN_SIGNING_VERSION"


def test_unknown_future_signing_version_is_rejected(tenant, package):
    result = verify(tenant, package, signing_version="OBJECT_SIGNING_KEY_V99")
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_UNKNOWN_SIGNING_VERSION"


# --------------------------------------------------------------- signing


def test_genuine_v1_package_verifies(tenant, package):
    assert verify(tenant, package).valid is True


def test_signing_uses_the_configured_secret_not_the_tenant_id(tenant, package, settings):
    settings.DAWATRACE_OBJECT_SIGNING_KEY = "a-completely-different-secret"
    assert verify(tenant, package).valid is False


def test_verification_fails_closed_without_a_signing_key(tenant, package, settings):
    """A misconfigured deployment must refuse packages, not accept them."""
    settings.DAWATRACE_OBJECT_SIGNING_KEY = ""
    result = verify(tenant, package)
    assert result.valid is False


@pytest.mark.parametrize(
    "field, value",
    [
        ("expires_at", "2099-01-01T00:00:00+00:00"),
        ("context_hash", "tampered"),
        ("permitted_actions", ["DISPENSE_CONTROLLED"]),
        ("tenant_id", str(uuid.uuid4())),
        ("branch_id", str(uuid.uuid4())),
        ("device_id", "SOME-OTHER-TILL"),
        ("findings_digest", "0" * 64),
        ("nonce", str(uuid.uuid4())),
    ],
)
def test_any_mutation_of_the_signed_payload_invalidates_it(tenant, package, field, value):
    """Everything security-relevant is inside the signature.

    A field left outside could be edited on a device without detection.
    """
    tampered = dict(package.package_data)
    tampered[field] = value
    result = verify(tenant, package, package_data=tampered)
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_INVALID_SIGNATURE"


def test_canonical_encoding_is_order_independent():
    """Signing non-deterministic JSON would produce spurious failures."""
    a = {"b": 2, "a": 1, "c": [3, 1]}
    b = {"c": [3, 1], "a": 1, "b": 2}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_signature_is_domain_separated():
    """A signature over some other object type must not replay as a package."""
    assert canonical_bytes({}).startswith(SIGNING_DOMAIN.encode())


# --------------------------------------------------------------- binding


@pytest.mark.parametrize(
    "kwarg, value, code",
    [
        ("expected_device_id", "OTHER-TILL", "OFFLINE_PACKAGE_WRONG_DEVICE"),
        ("expected_context_hash", "different-ctx", "OFFLINE_PACKAGE_STALE_CONTEXT"),
        ("expected_branch_id", str(uuid.uuid4()), "OFFLINE_PACKAGE_WRONG_BRANCH"),
    ],
)
def test_package_is_bound_to_its_issued_context(tenant, package, kwarg, value, code):
    result = verify(tenant, package, **{kwarg: value})
    assert result.valid is False
    assert result.code == code


def test_package_is_bound_to_its_tenant(tenant, package):
    other = Tenant.objects.create(name="Other", slug="other-co")
    result = verify(other, package)
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_WRONG_TENANT"


# --------------------------------------------------------------- expiry


def test_expired_package_does_not_verify(tenant, package):
    PosOfflineClinicalPackage.all_objects.filter(pk=package.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    package.refresh_from_db()
    result = verify(tenant, package, package=package)
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_EXPIRED"


def test_retrieval_never_returns_an_expired_package(tenant, package):
    """Previously the endpoint returned the newest package, expired or not."""
    PosOfflineClinicalPackage.all_objects.filter(pk=package.pk).update(
        expires_at=timezone.now() - timedelta(hours=1)
    )
    assert PosOfflinePackageService.get_valid_package(tenant=tenant) is None


def test_future_dated_package_is_rejected_beyond_tolerance(tenant, package):
    """Guards a tampered or badly-clocked issuer minting a long-lived package."""
    from apps.cds.offline_package_signing import verify_package_payload

    past = timezone.now() - timedelta(seconds=FUTURE_ISSUE_TOLERANCE_SECONDS + 120)
    result = verify_package_payload(
        payload=package.package_data,
        signature=package.signature,
        signing_version=package.signing_version,
        now=past,
    )
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_NOT_YET_VALID"


def test_valid_package_is_retrievable(tenant, package):
    assert PosOfflinePackageService.get_valid_package(tenant=tenant) is not None


# --------------------------------------------------------------- revocation


def test_revoked_package_does_not_verify(tenant, package):
    PosOfflinePackageService.revoke(package=package, reason="incident")
    package.refresh_from_db()
    result = verify(tenant, package, package=package)
    assert result.valid is False
    assert result.code == "OFFLINE_PACKAGE_REVOKED"


def test_revoked_package_is_not_retrievable(tenant, package):
    PosOfflinePackageService.revoke(package=package, reason="incident")
    assert PosOfflinePackageService.get_valid_package(tenant=tenant) is None


def test_revocation_retains_the_record_for_audit(tenant, package):
    PosOfflinePackageService.revoke(package=package, reason="incident")
    package.refresh_from_db()
    assert PosOfflineClinicalPackage.all_objects.filter(pk=package.pk).exists()
    assert package.revoked_at is not None
    assert package.revocation_reason == "incident"
    # The clinical payload is untouched: revocation changes trust, not history.
    assert package.package_data["package_id"] == str(package.pk)


def test_issuance_is_refused_over_an_unsafe_screening(tenant):
    """A package must never carry an offline authorisation the server would refuse."""
    from django.core.exceptions import ValidationError

    screening = type("S", (), {
        "safe_to_proceed": False,
        "context_hash": "ctx-abc",
        "patient_id": None,
        "prescription_id": None,
        "dispensing_episode_id": None,
        "pk": uuid.uuid4(),
    })()
    with pytest.raises(ValidationError, match="not safe to proceed"):
        PosOfflinePackageService.generate_package(tenant=tenant, screening=screening)
