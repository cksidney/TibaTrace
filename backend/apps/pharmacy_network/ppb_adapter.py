"""PPB (Pharmacy and Poisons Board) Premises & Superintendent Adapter.

Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED

This module provides the provider abstraction for PPB regulatory lookups.
Three operation modes:

  MANUAL_GOVERNED: Internal manual verification only. No external call.
    Truth label: MANUAL_INTERNAL_VERIFICATION

  SANDBOX_MOCK: Structured mock responses for sandbox / testing.
    Truth label: SANDBOX_EVIDENCE_ONLY
    NEVER use in production.

  OFFICIAL_API: Live PPB API calls. Requires Platform Owner activation.
    Truth label: Set by the activation decision record.
    Not currently connected. Raises PpbIntegrationDisabled until
    Platform Owner credentials are approved and activated.

Public-register lookup (web scraping) is STRICTLY FORBIDDEN by the programme.
Do not fetch, parse, or present data from public websites as official regulatory
evidence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Operation modes
# ---------------------------------------------------------------------------

class PpbOperationMode:
    MANUAL_GOVERNED = "MANUAL_GOVERNED"
    SANDBOX_MOCK = "SANDBOX_MOCK"
    OFFICIAL_API = "OFFICIAL_API"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PpbIntegrationDisabled(RuntimeError):
    """Raised when a PPB API call is attempted without Platform Owner activation.

    Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED
    """


class PpbLookupError(RuntimeError):
    """Raised on transient or structural PPB lookup failures."""


# ---------------------------------------------------------------------------
# Response data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PpbPremisesResult:
    licence_number: str
    is_recognised: bool
    status: str   # ACTIVE, SUSPENDED, REVOKED, EXPIRED, UNKNOWN
    expiry_date: date | None
    superintendent_name: str
    truth_label: str
    raw_payload_digest: str  # SHA-256 of raw response. NOT the response itself.


@dataclass(frozen=True)
class PpbSuperintendentResult:
    ppb_number: str
    full_name: str
    is_recognised: bool
    status: str
    truth_label: str
    raw_payload_digest: str


@dataclass(frozen=True)
class PpbProductStatusResult:
    registration_number: str
    product_name: str
    status: str   # CURRENTLY_VERIFIED, STALE, SUSPENDED, WITHDRAWN, EXPIRED, UNKNOWN, MATCH_REQUIRES_REVIEW, NOT_FOUND
    truth_label: str


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class PpbAdapter:
    """PPB Premises & Regulatory Products adapter.

    Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED (default, OFFICIAL_API mode).
                 MANUAL_INTERNAL_VERIFICATION (MANUAL_GOVERNED mode).
                 SANDBOX_EVIDENCE_ONLY (SANDBOX_MOCK mode).

    Only MANUAL_GOVERNED and SANDBOX_MOCK modes work without Platform Owner activation.
    """

    def __init__(
        self,
        *,
        mode: str = PpbOperationMode.MANUAL_GOVERNED,
        is_api_enabled: bool = False,
    ) -> None:
        self._mode = mode
        self._is_api_enabled = is_api_enabled

    @property
    def truth_label(self) -> str:
        if self._mode == PpbOperationMode.MANUAL_GOVERNED:
            return "MANUAL_INTERNAL_VERIFICATION"
        if self._mode == PpbOperationMode.SANDBOX_MOCK:
            return "SANDBOX_EVIDENCE_ONLY"
        if self._is_api_enabled:
            return "PPB_API_ACTIVE"  # Only set when activation confirmed.
        return "ADAPTER_SCAFFOLDED_NOT_CONNECTED"

    def _require_api(self) -> None:
        if not self._is_api_enabled or self._mode != PpbOperationMode.OFFICIAL_API:
            raise PpbIntegrationDisabled(
                "PPB API integration is not enabled. "
                "Platform Owner activation is required. "
                f"Truth label: {self.truth_label}"
            )

    def verify_premises(
        self,
        licence_number: str,
    ) -> PpbPremisesResult:
        """Verify a premises licence with PPB.

        MANUAL_GOVERNED: Returns a placeholder indicating manual review required.
        SANDBOX_MOCK: Returns a structured mock result.
        OFFICIAL_API: Raises PpbIntegrationDisabled until Platform Owner activation.
        """
        if self._mode == PpbOperationMode.MANUAL_GOVERNED:
            return PpbPremisesResult(
                licence_number=licence_number,
                is_recognised=False,
                status="MANUAL_REVIEW_REQUIRED",
                expiry_date=None,
                superintendent_name="",
                truth_label="MANUAL_INTERNAL_VERIFICATION",
                raw_payload_digest="",
            )
        if self._mode == PpbOperationMode.SANDBOX_MOCK:
            return PpbPremisesResult(
                licence_number=licence_number,
                is_recognised=True,
                status="ACTIVE",
                expiry_date=date(2026, 12, 31),
                superintendent_name="SANDBOX_SUPERINTENDENT",
                truth_label="SANDBOX_EVIDENCE_ONLY",
                raw_payload_digest="sandbox_mock_digest",
            )
        self._require_api()
        raise NotImplementedError(
            "PPB API premises lookup is not implemented. "
            f"Truth label: {self.truth_label}"
        )

    def verify_superintendent(
        self,
        ppb_number: str,
    ) -> PpbSuperintendentResult:
        """Verify a superintendent pharmacist with PPB."""
        if self._mode == PpbOperationMode.MANUAL_GOVERNED:
            return PpbSuperintendentResult(
                ppb_number=ppb_number,
                full_name="",
                is_recognised=False,
                status="MANUAL_REVIEW_REQUIRED",
                truth_label="MANUAL_INTERNAL_VERIFICATION",
                raw_payload_digest="",
            )
        if self._mode == PpbOperationMode.SANDBOX_MOCK:
            return PpbSuperintendentResult(
                ppb_number=ppb_number,
                full_name="SANDBOX_SUPERINTENDENT",
                is_recognised=True,
                status="ACTIVE",
                truth_label="SANDBOX_EVIDENCE_ONLY",
                raw_payload_digest="sandbox_mock_digest",
            )
        self._require_api()
        raise NotImplementedError(
            "PPB API superintendent lookup is not implemented. "
            f"Truth label: {self.truth_label}"
        )

    def get_product_status(
        self,
        registration_number: str,
    ) -> PpbProductStatusResult:
        """Get the regulatory status of a product by PPB registration number."""
        if self._mode == PpbOperationMode.MANUAL_GOVERNED:
            return PpbProductStatusResult(
                registration_number=registration_number,
                product_name="",
                status="MANUAL_VERIFICATION",
                truth_label="MANUAL_INTERNAL_VERIFICATION",
            )
        if self._mode == PpbOperationMode.SANDBOX_MOCK:
            return PpbProductStatusResult(
                registration_number=registration_number,
                product_name="SANDBOX_PRODUCT",
                status="CURRENTLY_VERIFIED",
                truth_label="SANDBOX_EVIDENCE_ONLY",
            )
        self._require_api()
        raise NotImplementedError(
            "PPB API product status lookup is not implemented. "
            f"Truth label: {self.truth_label}"
        )

    def get_regulatory_alerts(self) -> list[dict]:
        """Fetch current regulatory safety alerts.

        Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED
        Returns empty list; no regulator feed is connected.
        """
        if self._mode == PpbOperationMode.OFFICIAL_API and self._is_api_enabled:
            self._require_api()
            raise NotImplementedError("PPB Regulatory Alerts API not implemented.")
        return []  # LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED

    def get_recall_notices(self) -> list[dict]:
        """Fetch current product recall notices.

        Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED
        Returns empty list; no regulator feed is connected.
        """
        if self._mode == PpbOperationMode.OFFICIAL_API and self._is_api_enabled:
            self._require_api()
            raise NotImplementedError("PPB Recall Notices API not implemented.")
        return []  # LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED


# Module-level adapter instance (MANUAL_GOVERNED mode by default).
PPB_ADAPTER = PpbAdapter(mode=PpbOperationMode.MANUAL_GOVERNED, is_api_enabled=False)
