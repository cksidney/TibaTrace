"""Deterministic fake insurer.

Used by tests and by development environments. Every scenario is chosen
explicitly and produces the same answer every time: a fake that picks outcomes
at random makes a suite that fails once a week and gets retried rather than
read.

It exists mainly to exercise the states real insurers put us in that are easy to
forget -- accepted-then-silent, partial approval, duplicate, and the timeout
where we genuinely do not know whether the claim landed.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from .base import (
    AdapterLineOutcome,
    AdapterResult,
    BusinessState,
    TransportState,
    register_adapter,
)


class Scenario:
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    COVERAGE_EXPIRED = "COVERAGE_EXPIRED"
    FULL_APPROVAL = "FULL_APPROVAL"
    PARTIAL_APPROVAL = "PARTIAL_APPROVAL"
    PREAUTH_REQUIRED = "PREAUTH_REQUIRED"
    PREAUTH_REJECTED = "PREAUTH_REJECTED"
    CLAIM_ACCEPTED_PENDING = "CLAIM_ACCEPTED_PENDING"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    DUPLICATE = "DUPLICATE"
    TIMEOUT = "TIMEOUT"
    OUTAGE = "OUTAGE"
    MALFORMED = "MALFORMED"


def _digest(payload: Any) -> str:
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


class FakeInsurerAdapter:
    """A configurable, deterministic insurer."""

    insurer_code = "FAKE"

    def __init__(self, *, scenario: str = Scenario.FULL_APPROVAL):
        self.scenario = scenario
        #: Idempotency keys already seen, so a replay is reported as a
        #: duplicate rather than silently creating a second claim.
        self._seen_keys: dict[str, AdapterResult] = {}

    # ------------------------------------------------------------- coverage

    def verify_coverage(self, *, request: dict[str, Any]) -> AdapterResult:
        if self.scenario == Scenario.COVERAGE_EXPIRED:
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.REJECTED,
                response_code="COVERAGE_EXPIRED",
                response_message="Coverage lapsed before the service date.",
                raw_response_digest=_digest(request),
            )
        if self.scenario == Scenario.INELIGIBLE:
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.REJECTED,
                response_code="NOT_ELIGIBLE",
                response_message="Member is not eligible for this benefit.",
                raw_response_digest=_digest(request),
            )
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.APPROVED,
            external_reference="FAKE-COV-1",
            response_code="ELIGIBLE",
            raw_response_digest=_digest(request),
        )

    def check_eligibility(self, *, request: dict[str, Any]) -> AdapterResult:
        return self.verify_coverage(request=request)

    # -------------------------------------------------------- preauthorisation

    def submit_preauthorisation(self, *, request: dict[str, Any]) -> AdapterResult:
        if self.scenario == Scenario.PREAUTH_REJECTED:
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.REJECTED,
                external_reference="FAKE-PA-REJ",
                response_code="NON_FORMULARY",
                raw_response_digest=_digest(request),
            )
        if self.scenario == Scenario.PARTIAL_APPROVAL:
            lines = tuple(
                AdapterLineOutcome(
                    line_reference=str(line.get("line_reference", "")),
                    claimed_amount=Decimal(str(line.get("amount", "0"))),
                    approved_amount=Decimal(str(line.get("amount", "0"))) / 2,
                    approved_quantity=Decimal(str(line.get("quantity", "0"))) / 2,
                    status=BusinessState.PARTIALLY_APPROVED,
                    reason_code="QUANTITY_LIMIT",
                )
                for line in request.get("lines", [])
            )
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.PARTIALLY_APPROVED,
                external_reference="FAKE-PA-PART",
                lines=lines,
                raw_response_digest=_digest(request),
            )
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.APPROVED,
            external_reference="FAKE-PA-OK",
            raw_response_digest=_digest(request),
        )

    def check_preauthorisation(self, *, reference: str) -> AdapterResult:
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.APPROVED,
            external_reference=reference,
        )

    # ----------------------------------------------------------------- claims

    def submit_claim(self, *, request: dict[str, Any], idempotency_key: str) -> AdapterResult:
        # A retried network call must not produce a second claim.
        if idempotency_key in self._seen_keys:
            previous = self._seen_keys[idempotency_key]
            return AdapterResult(
                transport_state=previous.transport_state,
                business_state=BusinessState.DUPLICATE,
                external_reference=previous.external_reference,
                response_code="DUPLICATE_SUBMISSION",
                response_message="This claim was already submitted.",
                raw_response_digest=previous.raw_response_digest,
            )

        result = self._claim_result(request)
        # Only cache outcomes that actually reached the insurer. A timeout tells
        # us nothing, so a retry must be allowed to try again.
        if result.reached_insurer:
            self._seen_keys[idempotency_key] = result
        return result

    def _claim_result(self, request: dict[str, Any]) -> AdapterResult:
        digest = _digest(request)
        lines = request.get("lines", [])

        if self.scenario == Scenario.TIMEOUT:
            # We do not know whether it landed. Retryable, and emphatically not
            # a rejection.
            return AdapterResult(
                transport_state=TransportState.TIMEOUT,
                business_state=BusinessState.UNKNOWN,
                response_message="No response within the timeout.",
                retryable=True,
            )
        if self.scenario == Scenario.OUTAGE:
            return AdapterResult(
                transport_state=TransportState.UNAVAILABLE,
                business_state=BusinessState.UNKNOWN,
                response_code="503",
                retryable=True,
            )
        if self.scenario == Scenario.MALFORMED:
            return AdapterResult(
                transport_state=TransportState.MALFORMED_RESPONSE,
                business_state=BusinessState.UNKNOWN,
                response_message="Response could not be parsed.",
                retryable=False,
            )
        if self.scenario == Scenario.CLAIM_REJECTED:
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.REJECTED,
                external_reference="FAKE-CLM-REJ",
                response_code="MEMBER_INELIGIBLE",
                raw_response_digest=digest,
            )
        if self.scenario == Scenario.MORE_INFORMATION_REQUIRED:
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.MORE_INFORMATION_REQUIRED,
                external_reference="FAKE-CLM-INFO",
                response_code="ATTACHMENT_REQUIRED",
                raw_response_digest=digest,
            )
        if self.scenario == Scenario.CLAIM_ACCEPTED_PENDING:
            # The dangerous one: they have it, and have said nothing.
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.PENDING,
                external_reference="FAKE-CLM-PEND",
                raw_response_digest=digest,
            )
        if self.scenario == Scenario.PARTIAL_APPROVAL:
            outcomes = tuple(
                AdapterLineOutcome(
                    line_reference=str(line.get("line_reference", "")),
                    claimed_amount=Decimal(str(line.get("amount", "0"))),
                    allowed_amount=Decimal(str(line.get("amount", "0"))) * Decimal("0.8"),
                    approved_amount=Decimal(str(line.get("amount", "0"))) * Decimal("0.8"),
                    disallowed_amount=Decimal(str(line.get("amount", "0"))) * Decimal("0.2"),
                    reason_code="TARIFF_LIMIT",
                    status=BusinessState.PARTIALLY_APPROVED,
                )
                for line in lines
            )
            total = sum((o.approved_amount for o in outcomes), Decimal("0.00"))
            return AdapterResult(
                transport_state=TransportState.ACCEPTED,
                business_state=BusinessState.PARTIALLY_APPROVED,
                external_reference="FAKE-CLM-PART",
                approved_amount=total,
                lines=outcomes,
                raw_response_digest=digest,
            )

        outcomes = tuple(
            AdapterLineOutcome(
                line_reference=str(line.get("line_reference", "")),
                claimed_amount=Decimal(str(line.get("amount", "0"))),
                allowed_amount=Decimal(str(line.get("amount", "0"))),
                approved_amount=Decimal(str(line.get("amount", "0"))),
                status=BusinessState.APPROVED,
            )
            for line in lines
        )
        total = sum((o.approved_amount for o in outcomes), Decimal("0.00"))
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.APPROVED,
            external_reference="FAKE-CLM-OK",
            approved_amount=total,
            lines=outcomes,
            raw_response_digest=digest,
        )

    def check_claim(self, *, reference: str) -> AdapterResult:
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.PENDING,
            external_reference=reference,
        )

    def resubmit_claim(self, *, request: dict[str, Any], idempotency_key: str) -> AdapterResult:
        return self.submit_claim(request=request, idempotency_key=idempotency_key)

    def reverse_claim(self, *, reference: str, reason: str, idempotency_key: str) -> AdapterResult:
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.REVERSED,
            external_reference=reference,
            response_message=reason,
        )

    def fetch_remittance(self, *, since: str) -> AdapterResult:
        return AdapterResult(
            transport_state=TransportState.ACCEPTED,
            business_state=BusinessState.UNKNOWN,
            extra={"since": since, "remittances": []},
        )


register_adapter(FakeInsurerAdapter.insurer_code, FakeInsurerAdapter)
