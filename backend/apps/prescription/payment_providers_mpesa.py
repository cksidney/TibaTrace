"""M-PESA (Safaricom Daraja) payment adapter.

Implements the provider-neutral contract in payment_providers.py against the
Daraja STK-push API. Everything provider-specific stays behind that contract:
the payment domain never sees a Daraja field name.

Credentials are never read from the bundle or hard-coded. They come from the
tenant's configuration, and the adapter refuses to operate without them rather
than falling back to a default -- a default credential is a shared credential.

Status: written against the published Daraja contract and unit-tested with
recorded response shapes. It has NOT been exercised against Safaricom's sandbox
or production. Until it has, MPESA stays out of the adapter registry, so a
tender cannot be routed to it by configuration alone.
"""
from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any

from apps.prescription.payment_providers import InitiationResult, ProviderEvent

DARAJA_SANDBOX = "https://sandbox.safaricom.co.ke"
DARAJA_PRODUCTION = "https://api.safaricom.co.ke"


@dataclass(frozen=True)
class MpesaConfig:
    """Per-tenant Daraja configuration.

    Held as a value object so credentials are passed explicitly rather than read
    from module state, which makes it obvious at every call site whose money is
    being moved.
    """

    consumer_key: str
    consumer_secret: str
    short_code: str
    passkey: str
    callback_url: str
    environment: str = "sandbox"

    def __post_init__(self) -> None:
        missing = [
            name
            for name in ("consumer_key", "consumer_secret", "short_code", "passkey", "callback_url")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"M-PESA configuration is incomplete: {', '.join(missing)}. "
                "A partially configured provider must not be used."
            )
        if self.environment not in {"sandbox", "production"}:
            raise ValueError(f"Unknown M-PESA environment: {self.environment}")
        if self.environment == "production" and not self.callback_url.startswith("https://"):
            # Daraja posts settlement notifications here. Over plain HTTP they
            # can be read and altered in transit.
            raise ValueError("The M-PESA callback URL must use HTTPS in production.")

    @property
    def base_url(self) -> str:
        return DARAJA_SANDBOX if self.environment == "sandbox" else DARAJA_PRODUCTION


def normalise_msisdn(raw: str) -> str:
    """Normalise a Kenyan mobile number to Daraja's 2547XXXXXXXX form.

    Operators key numbers in every plausible way. Sending an unnormalised one
    produces a push to nobody, which reads to the operator as a customer who
    did not respond.
    """
    digits = "".join(character for character in str(raw) if character.isdigit())
    if digits.startswith("254"):
        candidate = digits
    elif digits.startswith("0"):
        candidate = f"254{digits[1:]}"
    elif len(digits) == 9:
        candidate = f"254{digits}"
    else:
        raise ValueError(f"Not a recognisable Kenyan mobile number: {raw!r}")

    if len(candidate) != 12 or not candidate.startswith(("2547", "2541")):
        raise ValueError(f"Not a recognisable Kenyan mobile number: {raw!r}")
    return candidate


def stk_password(short_code: str, passkey: str, timestamp: str) -> str:
    """Daraja's password: base64(shortcode + passkey + timestamp)."""
    return base64.b64encode(f"{short_code}{passkey}{timestamp}".encode()).decode()


def daraja_timestamp(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(dt_timezone.utc)
    return moment.strftime("%Y%m%d%H%M%S")


class MpesaAdapter:
    """Daraja STK-push adapter.

    The HTTP transport is injected so the adapter can be exercised against
    recorded responses without reaching Safaricom, and so the caller owns
    timeouts and retries.
    """

    provider_code = "MPESA"

    def __init__(self, *, config: MpesaConfig, transport=None):
        self.config = config
        # A callable (method, url, headers, json) -> (status, body dict).
        self._transport = transport

    # ------------------------------------------------------------------ config

    def validate_configuration(self, *, tenant, branch=None) -> None:  # noqa: ARG002
        # MpesaConfig validates on construction; this exists so a misconfigured
        # tenant fails at setup rather than at the till.
        if not self.config.consumer_key or not self.config.consumer_secret:
            raise ValueError("M-PESA credentials are not configured for this tenant.")

    # ---------------------------------------------------------------- initiate

    def initiate(self, *, attempt, context: dict[str, Any]) -> InitiationResult:
        """Send an STK push. Records only that the customer was asked."""
        try:
            msisdn = normalise_msisdn(context.get("phone_number", ""))
        except ValueError as exc:
            return InitiationResult(
                accepted=False,
                request_reference=attempt.request_reference,
                failure_code="INVALID_PHONE_NUMBER",
                failure_reason=str(exc),
                retryable=False,
            )

        amount = Decimal(str(attempt.requested_amount))
        if amount != amount.to_integral_value():
            # Daraja accepts whole shillings only. Rounding here would collect a
            # different sum from the one recorded against the tender.
            return InitiationResult(
                accepted=False,
                request_reference=attempt.request_reference,
                failure_code="AMOUNT_NOT_WHOLE",
                failure_reason="M-PESA accepts whole shillings only.",
                retryable=False,
            )

        timestamp = daraja_timestamp()
        payload = {
            "BusinessShortCode": self.config.short_code,
            "Password": stk_password(self.config.short_code, self.config.passkey, timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": msisdn,
            "PartyB": self.config.short_code,
            "PhoneNumber": msisdn,
            "CallBackURL": self.config.callback_url,
            # Our reference travels with the request, so a callback arriving
            # before the initiation response can still be matched.
            "AccountReference": attempt.request_reference[:12],
            "TransactionDesc": "Pharmacy dispensing",
        }

        try:
            status, body = self._post("/mpesa/stkpush/v1/processrequest", payload)
        except Exception as exc:  # noqa: BLE001 - transport failures are normalised
            return InitiationResult(
                accepted=False,
                request_reference=attempt.request_reference,
                failure_code="PROVIDER_UNAVAILABLE",
                failure_reason=str(exc),
                # Nothing was collected, so retrying is safe.
                retryable=True,
            )

        return self._interpret_initiation(attempt, status, body)

    def _interpret_initiation(self, attempt, status: int, body: dict[str, Any]) -> InitiationResult:
        response_code = str(body.get("ResponseCode", ""))
        if status == 200 and response_code == "0":
            return InitiationResult(
                accepted=True,
                provider_reference=str(body.get("CheckoutRequestID", "")),
                request_reference=attempt.request_reference,
                provider_status="ACCEPTED",
                customer_message=str(body.get("CustomerMessage", "")),
            )

        code = str(body.get("errorCode") or response_code or f"HTTP_{status}")
        reason = str(body.get("errorMessage") or body.get("ResponseDescription") or "Request refused.")
        return InitiationResult(
            accepted=False,
            request_reference=attempt.request_reference,
            failure_code=code,
            failure_reason=reason,
            # 5xx and throttling may succeed later; a refusal will not.
            retryable=status >= 500 or code in {"500.001.1001"},
        )

    # ------------------------------------------------------------------- query

    def query_status(self, *, attempt) -> ProviderEvent | None:
        """Poll Daraja. Used when a callback never arrives."""
        timestamp = daraja_timestamp()
        payload = {
            "BusinessShortCode": self.config.short_code,
            "Password": stk_password(self.config.short_code, self.config.passkey, timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": attempt.provider_reference,
        }
        try:
            _status, body = self._post("/mpesa/stkpushquery/v1/query", payload)
        except Exception:  # noqa: BLE001
            # Unknown is not failure. Reporting failure here would let a till
            # abandon a payment the customer had actually completed.
            return None

        result_code = str(body.get("ResultCode", ""))
        return ProviderEvent(
            provider_reference=attempt.provider_reference,
            request_reference=attempt.request_reference,
            event_type="PAYMENT",
            status="SUCCEEDED" if result_code == "0" else "FAILED" if result_code else "PENDING",
            amount=Decimal(str(attempt.requested_amount)) if result_code == "0" else None,
            event_id=f"QUERY-{attempt.provider_reference}",
            raw_status=result_code,
        )

    # ------------------------------------------------------------------ events

    def authenticate_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> bool:
        """Authenticate an inbound callback.

        Daraja does not sign its callbacks, so authenticity rests on the
        callback URL being unguessable and on source restriction at the edge.
        This checks a shared secret placed in the URL path or header by our own
        infrastructure -- it is a real check, but it is not a provider
        signature, and the deployment must also restrict source addresses.
        """
        expected = getattr(self.config, "callback_secret", "") or ""
        if not expected:
            # No secret configured means we cannot tell a genuine callback from
            # a forged one, so nothing is accepted.
            return False
        supplied = str(headers.get("X-Callback-Token", ""))
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def parse_event(self, *, headers: dict[str, str], payload: dict[str, Any]) -> ProviderEvent:  # noqa: ARG002
        """Flatten Daraja's nested callback into the neutral event shape."""
        body = payload.get("Body", {}).get("stkCallback", payload)
        metadata = {
            item.get("Name"): item.get("Value")
            for item in body.get("CallbackMetadata", {}).get("Item", [])
            if isinstance(item, dict)
        }

        result_code = str(body.get("ResultCode", ""))
        amount = metadata.get("Amount")
        receipt = str(metadata.get("MpesaReceiptNumber") or "")

        return ProviderEvent(
            provider_reference=str(body.get("CheckoutRequestID", "")),
            # Daraja echoes our AccountReference only on some product types, so
            # matching falls back to the checkout id the initiation recorded.
            request_reference=str(metadata.get("AccountReference") or ""),
            event_type="PAYMENT",
            status="SUCCEEDED" if result_code == "0" else "FAILED",
            amount=Decimal(str(amount)) if amount is not None else None,
            currency="KES",
            account_reference=str(metadata.get("PhoneNumber") or ""),
            # The receipt number is Daraja's own unique id for the payment, so
            # it is what makes duplicate delivery detectable.
            event_id=receipt or str(body.get("CheckoutRequestID", "")),
            raw_status=result_code,
            extra={"result_desc": str(body.get("ResultDesc", ""))},
        )

    # --------------------------------------------------------------- transport

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self._transport is None:
            raise RuntimeError(
                "No HTTP transport is configured for the M-PESA adapter. "
                "It cannot reach Safaricom."
            )
        return self._transport(
            "POST",
            f"{self.config.base_url}{path}",
            {"Content-Type": "application/json"},
            json.loads(json.dumps(payload)),
        )
