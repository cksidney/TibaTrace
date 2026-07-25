"""Provider-neutral payment adapters.

A provider is anything that can be asked for money and later reports whether it
arrived: M-PESA, a card gateway, or the deterministic fake used in tests and
demos.

Two rules shape this module, and they are the reason it exists separately from
the ledger:

1. Initiation is not settlement. `initiate()` records only that we asked. Money
   is confirmed solely by a provider event that produces a PaymentSettlement.
   A provider that returns "accepted" has told us nothing about whether the
   customer paid.
2. Provider-specific shapes never escape. Every adapter returns the same
   normalised result, so a quirk of one gateway's JSON cannot leak into the
   payment domain and start driving business decisions.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class InitiationResult:
    """Normalised outcome of asking a provider to collect."""

    accepted: bool
    provider_reference: str = ""
    request_reference: str = ""
    provider_status: str = ""
    customer_message: str = ""
    retryable: bool = False
    failure_code: str = ""
    failure_reason: str = ""


@dataclass(frozen=True)
class ProviderEvent:
    """Normalised inbound notification or polled status."""

    provider_reference: str
    request_reference: str
    event_type: str
    #: SUCCEEDED | FAILED | PENDING | CANCELLED
    status: str
    amount: Decimal | None = None
    currency: str = ""
    account_reference: str = ""
    occurred_at: str = ""
    #: Provider-assigned id. What makes duplicate delivery detectable.
    event_id: str = ""
    raw_status: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class PaymentProviderAdapter(Protocol):
    """Contract every provider implements."""

    provider_code: str

    def validate_configuration(self, *, tenant, branch=None) -> None: ...

    def initiate(self, *, attempt, context: dict[str, Any]) -> InitiationResult: ...

    def query_status(self, *, attempt) -> ProviderEvent | None: ...

    def authenticate_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> bool: ...

    def parse_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> ProviderEvent: ...


class FakeProviderScenario:
    """Deterministic scenarios the fake provider can be told to perform.

    Explicit rather than random: a test that sometimes passes is worse than no
    test, and a demo that behaves differently each run cannot be reasoned about.
    """

    IMMEDIATE_SUCCESS = "IMMEDIATE_SUCCESS"
    PENDING_THEN_SUCCESS = "PENDING_THEN_SUCCESS"
    DECLINED = "DECLINED"
    TIMEOUT = "TIMEOUT"
    DUPLICATE_CALLBACK = "DUPLICATE_CALLBACK"
    CALLBACK_BEFORE_INITIATION_RESPONSE = "CALLBACK_BEFORE_INITIATION_RESPONSE"
    WRONG_AMOUNT = "WRONG_AMOUNT"
    WRONG_ACCOUNT = "WRONG_ACCOUNT"
    LATE_SUCCESS = "LATE_SUCCESS"
    REVERSAL_SUCCESS = "REVERSAL_SUCCESS"
    REVERSAL_FAILURE = "REVERSAL_FAILURE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"

    ALL = frozenset(
        {
            IMMEDIATE_SUCCESS,
            PENDING_THEN_SUCCESS,
            DECLINED,
            TIMEOUT,
            DUPLICATE_CALLBACK,
            CALLBACK_BEFORE_INITIATION_RESPONSE,
            WRONG_AMOUNT,
            WRONG_ACCOUNT,
            LATE_SUCCESS,
            REVERSAL_SUCCESS,
            REVERSAL_FAILURE,
            PROVIDER_UNAVAILABLE,
        }
    )


class FakeProviderAdapter:
    """Deterministic provider for tests and demonstration environments.

    Never reaches the network. The scenario is chosen by the caller, so every
    failure path -- decline, timeout, duplicate delivery, wrong amount, late
    success -- can be exercised without depending on a third party being
    reachable or behaving badly on cue.
    """

    provider_code = "FAKE"

    #: Shared secret for event authentication. A real adapter reads this from
    #: the tenant's credential store; the fake keeps it explicit so the
    #: authentication path is genuinely exercised rather than stubbed out.
    def __init__(self, *, scenario: str = FakeProviderScenario.IMMEDIATE_SUCCESS, secret: str = "fake-secret"):
        if scenario not in FakeProviderScenario.ALL:
            raise ValueError(f"Unknown fake provider scenario: {scenario}")
        self.scenario = scenario
        self.secret = secret

    def validate_configuration(self, *, tenant, branch=None) -> None:  # noqa: ARG002
        if not self.secret:
            raise ValueError("Fake provider requires a secret.")

    def initiate(self, *, attempt, context: dict[str, Any]) -> InitiationResult:  # noqa: ARG002
        if self.scenario == FakeProviderScenario.PROVIDER_UNAVAILABLE:
            return InitiationResult(
                accepted=False,
                request_reference=attempt.request_reference,
                failure_code="PROVIDER_UNAVAILABLE",
                failure_reason="Provider is unreachable.",
                # Safe to retry: nothing was collected.
                retryable=True,
            )
        if self.scenario == FakeProviderScenario.DECLINED:
            return InitiationResult(
                accepted=False,
                request_reference=attempt.request_reference,
                failure_code="DECLINED",
                failure_reason="The customer declined the request.",
                retryable=False,
            )
        return InitiationResult(
            accepted=True,
            provider_reference=f"FAKE-{attempt.request_reference}",
            request_reference=attempt.request_reference,
            provider_status="ACCEPTED",
            customer_message="Approve the request on your handset.",
        )

    def query_status(self, *, attempt) -> ProviderEvent | None:
        """Poll. Used to reconcile when a callback never arrives."""
        if self.scenario in {
            FakeProviderScenario.TIMEOUT,
            FakeProviderScenario.PENDING_THEN_SUCCESS,
        }:
            return self._event(attempt, status="PENDING")
        if self.scenario == FakeProviderScenario.DECLINED:
            return self._event(attempt, status="FAILED")
        return self._event(attempt, status="SUCCEEDED")

    def authenticate_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> bool:
        """Constant-time comparison of a shared-secret signature.

        An unsigned or wrongly-signed event is refused outright: an inbound
        message that can be forged is a way to mint settlements.
        """
        supplied = str(headers.get("X-Fake-Signature", ""))
        expected = self.expected_signature(payload)
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def expected_signature(self, payload: dict[str, Any]) -> str:
        import hashlib
        import json

        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hmac.new(self.secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()

    def parse_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> ProviderEvent:  # noqa: ARG002
        amount = payload.get("amount")
        return ProviderEvent(
            provider_reference=str(payload.get("provider_reference") or ""),
            request_reference=str(payload.get("request_reference") or ""),
            event_type=str(payload.get("event_type") or "PAYMENT"),
            status=str(payload.get("status") or "PENDING"),
            amount=Decimal(str(amount)) if amount is not None else None,
            currency=str(payload.get("currency") or ""),
            account_reference=str(payload.get("account_reference") or ""),
            occurred_at=str(payload.get("occurred_at") or ""),
            event_id=str(payload.get("event_id") or ""),
            raw_status=str(payload.get("status") or ""),
        )

    def _event(self, attempt, *, status: str) -> ProviderEvent:
        amount = attempt.requested_amount
        if self.scenario == FakeProviderScenario.WRONG_AMOUNT:
            amount = amount - Decimal("1.00")
        account = "254700000000"
        if self.scenario == FakeProviderScenario.WRONG_ACCOUNT:
            account = "254799999999"
        return ProviderEvent(
            provider_reference=f"FAKE-{attempt.request_reference}",
            request_reference=attempt.request_reference,
            event_type="PAYMENT",
            status=status,
            amount=amount,
            account_reference=account,
            event_id=f"EVT-{attempt.request_reference}",
            raw_status=status,
        )


#: Registry. A provider becomes usable only once it is listed here, so an
#: unimplemented adapter cannot be selected by configuration alone.
ADAPTERS: dict[str, type] = {
    FakeProviderAdapter.provider_code: FakeProviderAdapter,
}


def get_adapter(provider_code: str, **kwargs):
    adapter = ADAPTERS.get(provider_code)
    if adapter is None:
        raise ValueError(
            f"No payment adapter is registered for {provider_code!r}. "
            "A tender cannot be settled through an unimplemented provider."
        )
    return adapter(**kwargs)
