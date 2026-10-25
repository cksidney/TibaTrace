"""Bounded DHA transport. Never expose provider response bodies in errors/logs."""
import hashlib
import json
import threading
import time
import weakref

import requests

from apps.integrations.dha_security import approved_url, secret


class DhaError(Exception):
    def __init__(self, code, status=None, retryable=False, uncertain=False):
        self.code, self.status = code, status
        self.retryable, self.uncertain = retryable, uncertain
        super().__init__(code)


_TOKENS = {}
_LOCK = threading.Lock()
_TOKEN_LOCKS = weakref.WeakValueDictionary()
MAX_RESPONSE = 2 * 1024 * 1024


class DhaClient:
    def __init__(self, connection):
        self.connection = connection
        self.config = connection.configuration

    def _request(self, method, path, *, headers=None, data=None, params=None, token=False, multipart=False, files=None):
        url = approved_url(self.config, path)
        # trust_env=False prevents environment proxy/netrc credentials from changing the destination/auth.
        try:
            form_parts = None
            if multipart:
                form_parts = [(k, (None, json.dumps(v) if isinstance(v, (dict, list)) else str(v))) for k, v in (data or {}).items()]
                form_parts.extend(files or [])
            with requests.Session() as session:
                session.trust_env = False
                with session.request(method, url, headers=headers, params=params, data=data if token else None,
                        json=data if not token and not multipart and method != "GET" else None, files=form_parts, timeout=(5, 25),
                        allow_redirects=False, verify=True, stream=True) as response:
                    status = response.status_code
                    if not 200 <= status < 300:
                        raise DhaError("AUTH_REJECTED" if status in (401, 403) else "PROVIDER_REJECTED",
                            status, retryable=status == 429 or (method == "GET" and status >= 500),
                            uncertain=method != "GET" and status >= 500)
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE:
                            raise DhaError("RESPONSE_TOO_LARGE", status, uncertain=method != "GET")
                    result = json.loads(body) if body else {}
                    if not isinstance(result, (dict, list)):
                        raise ValueError
                    if isinstance(result, dict) and (str(result.get("status", "")).lower() in {"error", "failed", "failure", "rejected"}
                            or result.get("success") is False or result.get("status") is False):
                        raise DhaError("BUSINESS_REJECTED", status)
                    return result, status
        except DhaError:
            raise
        except (requests.RequestException, ValueError, TypeError):
            raise DhaError("TRANSPORT_OR_RESPONSE_ERROR", retryable=method == "GET", uncertain=method != "GET") from None

    def token(self, force=False):
        client_id = secret(self.config.get("client_id_ref"))
        client_secret = secret(self.config.get("client_secret_ref"))
        key = hashlib.sha256(f"{self.connection.pk}:{self.connection.revision}:{client_id}:{client_secret}".encode()).hexdigest()
        with _LOCK:
            token_lock = _TOKEN_LOCKS.get(key)
            if token_lock is None:
                token_lock = threading.Lock()
                _TOKEN_LOCKS[key] = token_lock
        # Only token acquisition for this connection is serialized. A tenant's
        # stalled identity service must not block other tenants' cached tokens.
        with token_lock:
            with _LOCK:
                cached = _TOKENS.get(key)
            if not force and cached and cached[1] > time.monotonic():
                return cached[0]
            result, _ = self._request("POST", "/tenants/token", token=True,
                data={"client_id": client_id, "client_secret": client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            if not isinstance(result, dict):
                raise DhaError("INVALID_TOKEN_RESPONSE")
            token = result.get("access_token")
            try:
                lifetime = int(result.get("expires_in", 0))
            except (ValueError, TypeError):
                lifetime = 0
            if (not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token)
                    or str(result.get("token_type", "Bearer")).lower() != "bearer" or lifetime <= 0):
                raise DhaError("INVALID_TOKEN_RESPONSE")
            # Tokens stay in process memory only. Credential/config changes change the cache key.
            with _LOCK:
                for expired in [k for k, v in _TOKENS.items() if v[1] <= time.monotonic()]:
                    del _TOKENS[expired]
                if len(_TOKENS) > 1000:
                    _TOKENS.clear()
                _TOKENS[key] = (token, time.monotonic() + max(0, min(lifetime, 3600) - 30))
            return token

    def call(self, operation, path, payload, *, consent_token="", practitioner_id="", files=None):
        from apps.integrations.reliability import get_circuit_breaker
        breaker = get_circuit_breaker(f"DHA:{self.connection.pk}:{self.connection.revision}")
        if breaker.is_open():
            raise DhaError("CIRCUIT_OPEN", retryable=True)
        try:
            result = self._authorized_call(operation, path, payload, consent_token=consent_token,
                practitioner_id=practitioner_id, files=files)
        except DhaError as exc:
            if exc.status is None or exc.status >= 500:
                breaker.record_failure()
            raise
        breaker.record_success()
        return result

    def _authorized_call(self, operation, path, payload, *, consent_token="", practitioner_id="", files=None):
        headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/json",
            "X-Facility-Id": self.config["facility_id"], "X-Facility-Id-Type": "fr-code"}
        if consent_token:
            headers["X-Consent-Token"] = consent_token
        if practitioner_id:
            headers["X-PUID"] = practitioner_id
        try:
            return self._request(operation.method, path, headers=headers,
                params=payload if operation.method == "GET" else None, data=payload, multipart=operation.multipart, files=files)
        except DhaError as exc:
            # A read may refresh once after a token expiry. Never replay a mutation implicitly.
            if exc.status != 401 or operation.method != "GET":
                raise
            headers["Authorization"] = f"Bearer {self.token(force=True)}"
            return self._request("GET", path, headers=headers, params=payload)
