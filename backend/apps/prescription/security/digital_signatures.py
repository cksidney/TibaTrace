from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings


class SignatureFramework:
    """Phase 2 local signing boundary; production must use a configured KMS adapter."""

    algorithm = "HS256-PHASE2"

    @staticmethod
    def _key() -> bytes:
        key = str(settings.DAWATRACE_OBJECT_SIGNING_KEY or "")
        if not key:
            raise RuntimeError("A DawaTrace signing key is required.")
        return key.encode()

    @classmethod
    def sign_payload(cls, payload: dict) -> dict:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(cls._key(), encoded, hashlib.sha256).hexdigest()
        return {"algorithm": cls.algorithm, "key_identifier": "phase2-local", "signature": signature}

    @classmethod
    def verify_signature(cls, payload: dict, signature_envelope: dict) -> bool:
        if signature_envelope.get("algorithm") != cls.algorithm:
            return False
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        expected = hmac.new(cls._key(), encoded, hashlib.sha256).hexdigest()
        return hmac.compare_digest(str(signature_envelope.get("signature") or ""), expected)
