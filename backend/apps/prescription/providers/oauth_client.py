"""DHA Standards-Based OAuth 2.0 Client.

This module implements a fail-closed, credential-safe OAuth 2.0 client for
DHA national health system integrations.

SECURITY RULES (from the regulated programme):
1. Fail-closed: Missing credentials, invalid issuer/audience, TLS validation
   failure, or unapproved host MUST fail closed. Do not return a default token
   or silently succeed.
2. Credential masking: NEVER log client secrets, access tokens, refresh tokens,
   or private keys. Truncated identifiers only.
3. Host allow-listing: Connections are only permitted to pre-approved hosts
   listed in ProviderEndpoint.allowed_hosts. All other hosts fail closed.
4. Platform Owner gate: This client must only be invoked by code paths that
   have verified ProviderConfiguration.is_operational == True.

TRUTH LABEL: ADAPTER_SCAFFOLDED_NOT_CONNECTED
This client is scaffolded and structured but does NOT have active, approved
credentials for any live DHA endpoint. It will raise DhaIntegrationDisabled
for all real requests until Platform Owner approval is confirmed and live
credentials are supplied via the secrets manager.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DhaIntegrationDisabled(RuntimeError):
    """Raised when a DHA integration call is attempted without activation approval.

    Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED
    The adapter exists but has no approved credentials or Platform Owner activation.
    Do not catch this silently; it must surface as an operational alert.
    """


class DhaTokenError(RuntimeError):
    """Raised when token acquisition fails for a non-configuration reason (e.g. network, 4xx)."""


class DhaTlsHostError(RuntimeError):
    """Raised when the target host is not in the approved allow-list."""


# ---------------------------------------------------------------------------
# Token cache (in-process; production would use a distributed cache)
# ---------------------------------------------------------------------------

@dataclass
class _CachedToken:
    token_digest: str  # SHA-256 digest of the token for logging; never the token itself.
    expires_at: float  # Unix timestamp
    scopes: list[str] = field(default_factory=list)

    def is_valid(self, buffer_seconds: int = 60) -> bool:
        return time.monotonic() < (self.expires_at - buffer_seconds)


_TOKEN_CACHE: dict[str, _CachedToken] = {}


# ---------------------------------------------------------------------------
# Host allow-list enforcement
# ---------------------------------------------------------------------------

def _assert_allowed_host(url: str, allowed_hosts: list[str]) -> None:
    """Raise DhaTlsHostError unless the URL is HTTPS and its host is allowed.

    Fail-closed: an empty allow-list means no connections are permitted.
    """
    if not allowed_hosts:
        raise DhaTlsHostError(
            "No allowed hosts are configured for this provider endpoint. "
            "Connection refused (fail-closed)."
        )
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise DhaTlsHostError("OAuth token endpoints must use HTTPS. Connection refused (fail-closed).")
    if parsed.username or parsed.password:
        raise DhaTlsHostError("OAuth token endpoints must not contain user information.")
    host = parsed.hostname or ""
    if host not in allowed_hosts:
        raise DhaTlsHostError(
            f"Host '{host}' is not in the approved allow-list. Connection refused (fail-closed)."
        )


# ---------------------------------------------------------------------------
# OAuth client
# ---------------------------------------------------------------------------

class DhaOAuthClient:
    """Standards-based OAuth 2.0 client for DHA national health integrations.

    Usage:
        client = DhaOAuthClient(
            token_endpoint="https://auth.dha.go.ke/oauth/token",  # must be allow-listed
            client_id_reference="DHA_CLIENT_ID",   # env var / secrets-manager key
            client_secret_reference="DHA_CLIENT_SECRET",  # not-a-secret: environment variable name
            allowed_hosts=["auth.dha.go.ke"],
            expected_issuer="https://auth.dha.go.ke",
            expected_audience="dha-api",
        )
        token = client.get_access_token(scopes=["hwr:read"])

    CRITICAL: This client raises DhaIntegrationDisabled if `is_enabled=False`
    (the default). Set `is_enabled=True` ONLY when Platform Owner approval is
    confirmed and the ProviderConfiguration.activation_state == ACTIVE.
    """

    def __init__(
        self,
        *,
        token_endpoint: str,
        client_id_reference: str,
        client_secret_reference: str,
        allowed_hosts: list[str],
        expected_issuer: str,
        expected_audience: str,
        is_enabled: bool = False,
        truth_label: str = "ADAPTER_SCAFFOLDED_NOT_CONNECTED",
    ) -> None:
        self._token_endpoint = token_endpoint
        self._client_id_ref = client_id_reference
        self._client_secret_ref = client_secret_reference
        self._allowed_hosts = allowed_hosts
        self._expected_issuer = expected_issuer
        self._expected_audience = expected_audience
        self._is_enabled = is_enabled
        self._truth_label = truth_label

    def _resolve_secret(self, reference: str) -> str:
        """Resolve a credential reference to its secret value.

        In production this reads from the secrets manager (e.g. AWS Secrets
        Manager, HashiCorp Vault, GCP Secret Manager). Here it reads from
        the environment as a fallback for local/test environments.

        NEVER log the returned value.
        """
        import os
        value = os.environ.get(reference, "")
        if not value:
            raise DhaIntegrationDisabled(
                f"Credential reference '{reference}' is not resolved. "
                "Ensure credentials are configured in the secrets manager and approved by the Platform Owner. "
                f"Truth label: {self._truth_label}"
            )
        return value

    def get_access_token(self, scopes: list[str] | None = None) -> str:
        """Acquire an OAuth 2.0 access token.

        Returns the raw token string. NEVER log this value.
        Raises DhaIntegrationDisabled if the client is not enabled (fail-closed).
        Raises DhaTlsHostError if the token endpoint host is not allow-listed.
        Raises DhaTokenError if token acquisition fails.
        """
        if not self._is_enabled:
            raise DhaIntegrationDisabled(
                "DHA OAuth client is not enabled. Platform Owner activation is required. "
                f"Truth label: {self._truth_label}"
            )

        _assert_allowed_host(self._token_endpoint, self._allowed_hosts)

        scope_key = " ".join(sorted(scopes or []))
        cache_key = hashlib.sha256(
            f"{self._client_id_ref}:{self._token_endpoint}:{scope_key}".encode()
        ).hexdigest()

        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached.is_valid():
            logger.debug(
                "DHA OAuth: returning cached token (digest prefix: %s)",
                cached.token_digest[:8],
            )
            # We cannot return the digest; we must return the real token.
            # This architecture requires the real token to be stored temporarily.
            # For a full production implementation, use a distributed token store.
            # Here we raise to indicate the cache architecture needs wiring.
            raise NotImplementedError(
                "Token cache requires a distributed store for production use. "
                "Wire a proper token storage backend before enabling in production."
            )

        client_id = self._resolve_secret(self._client_id_ref)
        client_secret = self._resolve_secret(self._client_secret_ref)

        # Perform the token request with TLS verification, a strict timeout,
        # and redirects disabled so an allow-listed host cannot redirect token
        # credentials to a different origin.
        try:
            import requests

            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,  # noqa: S106 -- sent over TLS only
                "scope": scope_key,
                "audience": self._expected_audience,
            }
            response = requests.post(
                self._token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise DhaTokenError("OAuth token endpoint redirects are not permitted.")
            response.raise_for_status()
            body = response.json()

        except Exception as exc:  # noqa: BLE001
            # Never log the exception message directly; it may contain secrets.
            logger.error(
                "DHA OAuth: token request failed (provider: %s, error_class: %s). "
                "Check credentials in the secrets manager.",
                self._client_id_ref[:4] + "****",
                type(exc).__name__,
            )
            raise DhaTokenError(
                f"Token request failed: {type(exc).__name__}. Check credentials and endpoint."
            ) from exc

        access_token: str = body.get("access_token", "")
        if not access_token:
            raise DhaTokenError("Token response did not contain an access_token field.")

        expires_in: int = body.get("expires_in", 3600)
        token_digest = hashlib.sha256(access_token.encode()).hexdigest()

        _TOKEN_CACHE[cache_key] = _CachedToken(
            token_digest=token_digest,
            expires_at=time.monotonic() + expires_in,
            scopes=list(scopes or []),
        )

        logger.info(
            "DHA OAuth: token acquired (digest prefix: %s, expires_in: %ss).",
            token_digest[:8],
            expires_in,
        )
        # IMPORTANT: Only the token_digest is ever logged. The access_token is returned
        # directly to the caller and must not be logged by the caller either.
        return access_token

    @property
    def truth_label(self) -> str:
        return self._truth_label
