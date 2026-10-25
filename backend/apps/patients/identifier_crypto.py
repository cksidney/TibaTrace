"""Versioned patient identifier protection, independent of Django SECRET_KEY.

Fernet preserves identifier values. HKDF separates tenant and crypto purposes;
an independent HMAC keyring supplies lookup digests. Explicit historical service
secrets support legacy reads/migration only, never new encryption or hashing.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError

PREFIX = "ttid1:"
KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
SYSTEM_SCOPED_TYPES = {"OTHER", "HOSPITAL_NUMBER", "INSURANCE_NUMBER"}


class IdentifierProtectionError(ValueError):
    pass


def _decode(value):
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (AttributeError, UnicodeError, ValueError, binascii.Error):
        raise IdentifierProtectionError("Identifier keys must be base64url-encoded 32-byte values.") from None
    if len(raw) != 32:
        raise IdentifierProtectionError("Identifier keys must decode to 32 bytes.")
    return raw


def validate_identifier_keyrings(encryption, active_encryption, lookup, active_lookup, legacy):
    material = []
    for ring, active in ((encryption, active_encryption), (lookup, active_lookup)):
        if not isinstance(ring, dict) or not ring or len(ring) > 16:
            raise IdentifierProtectionError("A bounded independent identifier keyring is required for each purpose.")
        if not isinstance(active, str) or active not in ring:
            raise IdentifierProtectionError("Active identifier key is missing from its keyring.")
        for key_id, encoded in ring.items():
            if not isinstance(key_id, str) or not KEY_ID.fullmatch(key_id):
                raise IdentifierProtectionError("Identifier key ID is invalid.")
            material.append(_decode(encoded))
    if len(set(material)) != len(material):
        raise IdentifierProtectionError("Identifier key material must be distinct across IDs and purposes.")
    if not isinstance(legacy, list) or len(legacy) > 8 or any(not isinstance(s, str) or not s or len(s) > 4096 for s in legacy):
        raise IdentifierProtectionError("Legacy identifier secrets must be an explicit bounded list.")


class PatientIdentifierProtector:
    @staticmethod
    def configuration():
        encryption = getattr(settings, "DAWATRACE_PATIENT_IDENTIFIER_KEYS", {})
        active = getattr(settings, "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID", "")
        lookup = getattr(settings, "DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS", {})
        active_lookup = getattr(settings, "DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID", "")
        legacy = getattr(settings, "DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS", [])
        try:
            validate_identifier_keyrings(encryption, active, lookup, active_lookup, legacy)
        except IdentifierProtectionError:
            raise ValidationError("Patient identifier protection requires valid independent encryption and lookup keyrings.") from None
        return encryption, active, lookup, active_lookup, legacy

    @staticmethod
    def normalize(value):
        return "".join(str(value or "").strip().upper().split())

    @staticmethod
    def _derived(encoded, tenant_id, purpose):
        if not tenant_id:
            raise ValidationError("Patient identifier tenant scope is required.")
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"TibaTrace identifiers v1",
                    info=purpose + b"\x00" + str(tenant_id).encode("ascii")).derive(_decode(encoded))

    @classmethod
    def active_lookup_key_id(cls):
        return cls.configuration()[3]

    @classmethod
    def lookup_digests(cls, *, tenant_id, identifier_type, value, system=""):
        _, _, lookup, _, legacy = cls.configuration()
        normalized = cls.normalize(value)
        if not normalized:
            raise ValidationError({"value": "An identifier value is required."})
        kind = str(identifier_type).upper()
        namespace = str(system) if kind in SYSTEM_SCOPED_TYPES else ""
        lookup_value = str(value).strip() if kind in SYSTEM_SCOPED_TYPES else normalized
        message = (kind + "\x00" + namespace + "\x00" + lookup_value).encode()
        result = {kid: hmac.new(cls._derived(key, tenant_id, b"lookup"), message, hashlib.sha256).hexdigest()
                  for kid, key in lookup.items()}
        # Historical digests have no key-ID field. All explicit old secrets
        # remain lookup candidates until the complete migration is verified.
        old_message = (str(identifier_type).upper() + ":" + normalized).encode()
        historical = [hmac.new(f"{secret}:{tenant_id}".encode(), old_message, hashlib.sha256).hexdigest() for secret in legacy]
        return result, historical

    @classmethod
    def digest(cls, *, tenant_id, identifier_type, value, system=""):
        versions, _ = cls.lookup_digests(tenant_id=tenant_id, identifier_type=identifier_type, value=value, system=system)
        return versions[cls.active_lookup_key_id()]

    @classmethod
    def protect(cls, *, tenant_id, value):
        encryption, active, _, _, _ = cls.configuration()
        plaintext = str(value or "").strip()
        if not cls.normalize(plaintext):
            raise ValidationError({"value": "An identifier value is required."})
        if len(plaintext) > 255:
            raise ValidationError({"value": "An identifier value must not exceed 255 characters."})
        key = cls._derived(encryption[active], tenant_id, b"encryption")
        token = Fernet(base64.urlsafe_b64encode(key)).encrypt(plaintext.encode()).decode("ascii")
        return f"{PREFIX}{active}:{token}"

    @classmethod
    def reveal(cls, *, tenant_id, protected_value):
        encryption, _, _, _, legacy = cls.configuration()
        try:
            if protected_value.startswith(PREFIX):
                _, kid, token = protected_value.split(":", 2)
                key = cls._derived(encryption[kid], tenant_id, b"encryption")
                return Fernet(base64.urlsafe_b64encode(key)).decrypt(token.encode("ascii")).decode()
            for secret in legacy:
                key = base64.urlsafe_b64encode(hashlib.sha256(f"{secret}:patient-identifier:{tenant_id}".encode()).digest())
                try:
                    return Fernet(key).decrypt(protected_value.encode("ascii")).decode()
                except InvalidToken:
                    continue
        except (AttributeError, KeyError, InvalidToken, UnicodeError, ValueError):
            pass
        raise ValidationError("The protected identifier cannot be decrypted with the configured historical keys.")

    @classmethod
    def storage_fields(cls, *, tenant_id, identifier_type, value, system=""):
        normalized = cls.normalize(value)
        return {"value": "", "protected_value": cls.protect(tenant_id=tenant_id, value=value),
                "value_hash": cls.digest(tenant_id=tenant_id, identifier_type=identifier_type, value=value, system=system),
                "lookup_key_id": cls.active_lookup_key_id(), "last_four": normalized[-4:]}

    @classmethod
    def verified_plaintext(cls, identifier):
        """Internal migration/storage integrity check; never logs plaintext."""
        value = cls.reveal(tenant_id=identifier.tenant_id, protected_value=identifier.protected_value) if identifier.protected_value else str(identifier.value or "").strip()
        normalized = cls.normalize(value)
        if not normalized or len(value) > 255 or (identifier.value and str(identifier.value).strip() != value):
            raise ValidationError("Patient identifier content is missing or inconsistent.")
        if identifier.last_four and identifier.last_four != normalized[-4:]:
            raise ValidationError("Patient identifier masked suffix does not match protected content.")
        versions, historical = cls.lookup_digests(tenant_id=identifier.tenant_id, identifier_type=identifier.identifier_type, value=value, system=identifier.system)
        candidates = [versions.get(identifier.lookup_key_id, "")] if identifier.lookup_key_id else [*versions.values(), *historical]
        if identifier.value_hash and not any(hmac.compare_digest(identifier.value_hash, candidate) for candidate in candidates):
            raise ValidationError("Patient identifier lookup integrity could not be verified.")
        return value
