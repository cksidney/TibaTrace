"""Provider-neutral insurer contract.

Every insurer integration implements this and nothing else escapes it. The
domain never sees an insurer's field names, response codes or error strings,
because the moment one of those reaches a service, that insurer's quirks start
deciding clinical and financial outcomes for all of them.

The distinction this contract exists to preserve is **transport versus
business**. An HTTP 200 means the insurer received bytes. It does not mean the
claim was accepted, and it certainly does not mean it was approved or paid.
`AdapterResult` therefore carries both states separately and the domain maps
them to separate columns. Collapsing them is how a provider becomes a debtor for
money nobody ever agreed to pay.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


class TransportState:
    """Did the message reach the insurer?"""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class BusinessState:
    """What did the insurer decide?

    UNKNOWN is a first-class answer and the default. An insurer that accepted
    the bytes but told us nothing about the claim leaves us knowing nothing
    about the claim.
    """

    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    DUPLICATE = "DUPLICATE"
    REVERSED = "REVERSED"


@dataclass(frozen=True)
class AdapterLineOutcome:
    """Per-line decision. Insurers routinely approve some lines and not others."""

    line_reference: str
    claimed_amount: Decimal
    allowed_amount: Decimal = Decimal("0.00")
    approved_amount: Decimal = Decimal("0.00")
    approved_quantity: Decimal | None = None
    patient_liability: Decimal = Decimal("0.00")
    disallowed_amount: Decimal = Decimal("0.00")
    reason_code: str = ""
    reason_description: str = ""
    status: str = BusinessState.UNKNOWN


@dataclass(frozen=True)
class AdapterResult:
    """The single shape every adapter returns.

    `transport_state` and `business_state` are independent on purpose. The
    common and dangerous case is ACCEPTED + UNKNOWN: the insurer has our claim
    and has said nothing about it. That is not an approval and must never
    become a receivable.
    """

    transport_state: str
    business_state: str = BusinessState.UNKNOWN
    external_reference: str = ""
    correlation_reference: str = ""
    response_code: str = ""
    response_message: str = ""
    retryable: bool = False
    received_at: str = ""
    #: Digest rather than the body. Insurer payloads carry diagnoses and
    #: membership numbers, and this is stored on every attempt.
    raw_response_digest: str = ""
    approved_amount: Decimal | None = None
    lines: tuple[AdapterLineOutcome, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def reached_insurer(self) -> bool:
        return self.transport_state == TransportState.ACCEPTED

    @property
    def establishes_liability(self) -> bool:
        """Whether this result may create an insurer receivable.

        Only an explicit approval does. Transport acceptance never does, and
        neither does silence.
        """
        return self.reached_insurer and self.business_state in {
            BusinessState.APPROVED,
            BusinessState.PARTIALLY_APPROVED,
        }


class InsurerAdapter(Protocol):
    """What every insurer integration must provide."""

    insurer_code: str

    def verify_coverage(self, *, request: dict[str, Any]) -> AdapterResult: ...

    def check_eligibility(self, *, request: dict[str, Any]) -> AdapterResult: ...

    def submit_preauthorisation(self, *, request: dict[str, Any]) -> AdapterResult: ...

    def check_preauthorisation(self, *, reference: str) -> AdapterResult: ...

    def submit_claim(self, *, request: dict[str, Any], idempotency_key: str) -> AdapterResult: ...

    def check_claim(self, *, reference: str) -> AdapterResult: ...

    def resubmit_claim(self, *, request: dict[str, Any], idempotency_key: str) -> AdapterResult: ...

    def reverse_claim(self, *, reference: str, reason: str, idempotency_key: str) -> AdapterResult: ...

    def fetch_remittance(self, *, since: str) -> AdapterResult: ...


#: Adapters available for routing. An insurer configured to use a code that is
#: not here cannot transact -- the same rule the payment providers follow, and
#: for the same reason: a tender or a claim must never be routed to an
#: integration nobody has exercised.
ADAPTERS: dict[str, type] = {}


def register_adapter(code: str, adapter_class: type) -> None:
    ADAPTERS[code] = adapter_class


def get_adapter(insurer_code: str):
    adapter = ADAPTERS.get(insurer_code)
    if adapter is None:
        raise LookupError(
            f"No insurer adapter is registered for {insurer_code!r}. "
            "Claims cannot be submitted until one is implemented and registered."
        )
    return adapter
