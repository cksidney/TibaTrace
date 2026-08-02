"""DHA Health Worker Registry (HWR) Adapter.

Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED

The DHA Health Worker Registry is the authoritative source for Kenyan healthcare
practitioner registration and licence status. This adapter scaffolds the interface
for lookups by registration number, regulator body, and profession category.

Current state: Not connected. The adapter raises HwrIntegrationDisabled for all
live requests until Platform Owner activation is confirmed and approved credentials
are supplied via the secrets manager.

Practitioner Verification Lifecycle:
  UNVERIFIED: No verification attempted.
  PENDING: Verification request submitted; awaiting HWR response.
  VERIFIED: Confirmed by HWR (requires recent authoritative confirmation).
  STALE: Previously verified; confirmation is older than the configured freshness window.
  EXPIRED: Licence expired per HWR record.
  SUSPENDED: Licence suspended per HWR record.
  REVOKED: Licence revoked per HWR record.
  NOT_FOUND: No matching record in HWR.
  AMBIGUOUS: Multiple conflicting records returned.
  PROVIDER_UNAVAILABLE: HWR service is unreachable; degraded-mode logging applies.
  VERIFICATION_FAILED: HWR returned an error response.

Prescribibg Gate Rules:
- Routine prescribing: allows bounded cache period (configurable, default 90 days).
- Controlled medicine prescribing: requires VERIFIED state within CONTROLLED_FRESHNESS_DAYS.
- Degraded mode: outages recorded as PROVIDER_UNAVAILABLE decisions with audit trail.
- A STALE or PROVIDER_UNAVAILABLE practitioner may continue routine prescribing
  within the grace window; they CANNOT prescribe controlled substances.

Regulators supported:
  KMPDC: Kenya Medical Practitioners and Dentists Council
  COC: Council of Clinical Officers Kenya
  NCK: Nursing Council of Kenya
  PPB: Pharmacy and Poisons Board
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

ROUTINE_FRESHNESS_DAYS = 90    # Days a VERIFIED status is valid for routine prescribing.
CONTROLLED_FRESHNESS_DAYS = 7  # Days a VERIFIED status is valid for controlled medicines.

# ---------------------------------------------------------------------------
# Verification state
# ---------------------------------------------------------------------------

class HwrVerificationState:
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class Regulator:
    KMPDC = "KMPDC"
    COC = "COC"
    NCK = "NCK"
    PPB = "PPB"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HwrIntegrationDisabled(RuntimeError):
    """Raised when a HWR lookup is attempted without Platform Owner activation.

    Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED
    """


class HwrLookupError(RuntimeError):
    """Raised when a HWR lookup fails for a transient or structural reason."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HwrPractitionerRecord:
    """Normalized practitioner record from the DHA HWR."""
    registration_number: str
    full_name: str
    regulator: str
    profession: str
    licence_status: str  # ACTIVE, SUSPENDED, REVOKED, EXPIRED per HWR.
    licence_expiry: date | None
    prescribing_scope: list[str] = field(default_factory=list)
    controlled_medicine_authority: bool = False
    raw_payload_digest: str = ""  # SHA-256 of the raw response; not the payload itself.
    fetched_at: str = ""          # ISO datetime string.
    truth_label: str = "ADAPTER_SCAFFOLDED_NOT_CONNECTED"


@dataclass(frozen=True)
class HwrVerificationDecision:
    """The outcome of a practitioner verification check."""
    state: str
    can_prescribe_routine: bool
    can_prescribe_controlled: bool
    reason_codes: list[str]
    degraded_mode: bool  # True if HWR was unavailable; decision is a grace-period extension.
    truth_label: str


# ---------------------------------------------------------------------------
# Evidence logging
# ---------------------------------------------------------------------------

def record_hwr_evidence(
    *,
    practitioner_id: Any,
    tenant_id: Any,
    query_digest: str,
    outcome_state: str,
    degraded_mode: bool,
    truth_label: str,
    reason_codes: list[str],
) -> None:
    """Write an immutable HWR evidence log entry.

    The query_digest is a SHA-256 of the lookup parameters (never the raw query
    if it contains PII). The actual practitioner identifiers are referenced by
    practitioner_id only.
    """
    from apps.audit.service import log_audit
    log_audit(
        tenant_id=tenant_id,
        action="HWR_VERIFICATION_EVIDENCE",
        model_name="Practitioner",
        object_id=practitioner_id,
        metadata={
            "query_digest": query_digest,
            "outcome_state": outcome_state,
            "degraded_mode": degraded_mode,
            "truth_label": truth_label,
            "reason_codes": reason_codes,
        },
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class DhaHwrAdapter:
    """DHA Health Worker Registry adapter.

    Truth label: ADAPTER_SCAFFOLDED_NOT_CONNECTED

    All public methods raise HwrIntegrationDisabled when is_enabled=False
    (the default). Set is_enabled=True only when Platform Owner activation
    is confirmed and ProviderConfiguration.activation_state == ACTIVE.
    """

    def __init__(
        self,
        *,
        is_enabled: bool = False,
        truth_label: str = "ADAPTER_SCAFFOLDED_NOT_CONNECTED",
        routine_freshness_days: int = ROUTINE_FRESHNESS_DAYS,
        controlled_freshness_days: int = CONTROLLED_FRESHNESS_DAYS,
    ) -> None:
        self._is_enabled = is_enabled
        self._truth_label = truth_label
        self._routine_freshness_days = routine_freshness_days
        self._controlled_freshness_days = controlled_freshness_days

    def _guard(self) -> None:
        if not self._is_enabled:
            raise HwrIntegrationDisabled(
                "DHA HWR adapter is not enabled. Platform Owner activation is required. "
                f"Truth label: {self._truth_label}"
            )

    def lookup_by_registration_number(
        self,
        registration_number: str,
        regulator: str,
    ) -> HwrPractitionerRecord:
        """Look up a practitioner by registration number and regulator body.

        Raises HwrIntegrationDisabled until Platform Owner activation.
        Raises HwrLookupError on transient or structural errors.
        """
        self._guard()
        # In production: call DHA HWR API endpoint, parse response, return
        # normalized HwrPractitionerRecord.
        raise NotImplementedError(
            "DHA HWR API integration is not built. "
            f"Truth label: {self._truth_label}"
        )

    def compute_prescribing_decision(
        self,
        *,
        practitioner_id: Any,
        tenant_id: Any,
        verification_state: str,
        verified_at: object | None,
        controlled: bool = False,
    ) -> HwrVerificationDecision:
        """Apply risk-based prescribing gate rules.

        Does NOT contact HWR; this uses locally stored verification state.
        For a live check, call lookup_by_registration_number first.

        Rules:
          - VERIFIED within routine_freshness_days -> can prescribe routine.
          - VERIFIED within controlled_freshness_days -> can prescribe controlled.
          - STALE -> can prescribe routine (grace); CANNOT prescribe controlled.
          - PROVIDER_UNAVAILABLE -> degraded-mode extension; CANNOT prescribe controlled.
          - UNVERIFIED, PENDING, EXPIRED, SUSPENDED, REVOKED -> block all prescribing.
        """
        now = timezone.now()
        reason_codes: list[str] = []
        degraded_mode = (verification_state == HwrVerificationState.PROVIDER_UNAVAILABLE)

        if verification_state == HwrVerificationState.VERIFIED and verified_at:
            age_days = (now - verified_at).days if hasattr(verified_at, "days") else (
                (now - verified_at).total_seconds() / 86400
            )
            routine_ok = age_days <= self._routine_freshness_days
            controlled_ok = age_days <= self._controlled_freshness_days
            if not routine_ok:
                reason_codes.append("VERIFICATION_STALE_FOR_ROUTINE")
            if not controlled_ok:
                reason_codes.append("VERIFICATION_STALE_FOR_CONTROLLED")
            decision_state = (
                HwrVerificationState.VERIFIED if routine_ok else HwrVerificationState.STALE
            )
            can_routine = routine_ok
            can_controlled = controlled_ok
        elif verification_state == HwrVerificationState.STALE:
            reason_codes.append("VERIFICATION_STALE")
            decision_state = HwrVerificationState.STALE
            can_routine = True   # Grace period allowed for routine.
            can_controlled = False  # Controlled always requires fresh verification.
        elif verification_state == HwrVerificationState.PROVIDER_UNAVAILABLE:
            reason_codes.append("HWR_DEGRADED_MODE")
            decision_state = HwrVerificationState.PROVIDER_UNAVAILABLE
            can_routine = True   # Degrade gracefully for routine.
            can_controlled = False
        else:
            reason_codes.append(f"VERIFICATION_STATE_{verification_state}")
            decision_state = verification_state
            can_routine = False
            can_controlled = False

        query_digest = hashlib.sha256(
            f"{practitioner_id}:{verification_state}:{controlled}".encode()
        ).hexdigest()

        record_hwr_evidence(
            practitioner_id=practitioner_id,
            tenant_id=tenant_id,
            query_digest=query_digest,
            outcome_state=decision_state,
            degraded_mode=degraded_mode,
            truth_label=self._truth_label,
            reason_codes=reason_codes,
        )

        return HwrVerificationDecision(
            state=decision_state,
            can_prescribe_routine=can_routine,
            can_prescribe_controlled=can_controlled and (not controlled or can_controlled),
            reason_codes=reason_codes,
            degraded_mode=degraded_mode,
            truth_label=self._truth_label,
        )


# ---------------------------------------------------------------------------
# Module-level adapter instance (disabled by default; activated by Platform Owner)
# ---------------------------------------------------------------------------

DHA_HWR_ADAPTER = DhaHwrAdapter(
    is_enabled=False,
    truth_label="ADAPTER_SCAFFOLDED_NOT_CONNECTED",
)
