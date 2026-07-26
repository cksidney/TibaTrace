"""M-PESA (Daraja) adapter.

Exercised against recorded Daraja response shapes, never the network. These
tests pin the adapter's behaviour; they do not demonstrate that it works against
Safaricom, which requires sandbox credentials and a reachable callback URL.
"""
from decimal import Decimal

import pytest

from apps.prescription.payment_providers_mpesa import (
    MpesaAdapter,
    MpesaConfig,
    daraja_timestamp,
    normalise_msisdn,
    stk_password,
)


def config(**overrides):
    base = {
        "consumer_key": "key",
        "consumer_secret": "secret",
        "short_code": "174379",
        "passkey": "passkey",
        "callback_url": "https://tibatrace.example.test/api/pos/payments/mpesa/callback/",
        "environment": "sandbox",
    }
    base.update(overrides)
    return MpesaConfig(**base)


class FakeAttempt:
    def __init__(self, amount="1000", reference="REQ-abc123def456", provider_reference="ws_CO_1"):
        self.requested_amount = Decimal(amount)
        self.request_reference = reference
        self.provider_reference = provider_reference


def transport_returning(status, body):
    def _transport(method, url, headers, payload):  # noqa: ARG001
        return status, body

    return _transport


# ------------------------------------------------------------------- config


def test_incomplete_configuration_is_refused():
    """A partially configured provider must not be usable."""
    with pytest.raises(ValueError, match="incomplete"):
        MpesaConfig(
            consumer_key="key",
            consumer_secret="",
            short_code="174379",
            passkey="passkey",
            callback_url="https://example.test/cb",
        )


def test_production_requires_an_https_callback():
    """Daraja posts settlement notifications there; plain HTTP is readable."""
    with pytest.raises(ValueError, match="HTTPS"):
        config(environment="production", callback_url="http://example.test/cb")


def test_unknown_environment_is_refused():
    with pytest.raises(ValueError, match="Unknown M-PESA environment"):
        config(environment="staging")


def test_sandbox_and_production_use_different_hosts():
    assert "sandbox" in config().base_url
    assert "sandbox" not in config(environment="production").base_url


# ------------------------------------------------------------------ msisdn


@pytest.mark.parametrize(
    "raw",
    ["0712345678", "254712345678", "712345678", "+254 712 345 678", "0712 345 678"],
)
def test_phone_numbers_normalise_to_daraja_form(raw):
    """Operators key numbers every plausible way; an unnormalised one pushes to nobody."""
    assert normalise_msisdn(raw) == "254712345678"


@pytest.mark.parametrize("raw", ["12345", "", "abcdefghij", "25471234567890"])
def test_unrecognisable_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        normalise_msisdn(raw)


def test_a_bad_number_fails_initiation_without_calling_the_provider(monkeypatch):
    calls = []

    def _transport(*args):
        calls.append(args)
        return 200, {}

    adapter = MpesaAdapter(config=config(), transport=_transport)
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "nonsense"})

    assert result.accepted is False
    assert result.failure_code == "INVALID_PHONE_NUMBER"
    assert result.retryable is False
    assert calls == []


# ------------------------------------------------------------------ password


def test_password_is_base64_of_shortcode_passkey_timestamp():
    import base64

    encoded = stk_password("174379", "passkey", "20260101120000")
    assert base64.b64decode(encoded).decode() == "174379passkey20260101120000"


def test_timestamp_is_daraja_format():
    assert len(daraja_timestamp()) == 14
    assert daraja_timestamp().isdigit()


# ----------------------------------------------------------------- initiation


def test_accepted_push_returns_the_checkout_id():
    adapter = MpesaAdapter(
        config=config(),
        transport=transport_returning(
            200,
            {
                "ResponseCode": "0",
                "CheckoutRequestID": "ws_CO_010120261200",
                "CustomerMessage": "Success. Request accepted for processing",
            },
        ),
    )
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})

    assert result.accepted is True
    assert result.provider_reference == "ws_CO_010120261200"
    assert "accepted" in result.customer_message.lower()


def test_acceptance_is_not_settlement():
    """The customer has been asked. Nothing says they paid."""
    adapter = MpesaAdapter(
        config=config(),
        transport=transport_returning(200, {"ResponseCode": "0", "CheckoutRequestID": "ws_CO_1"}),
    )
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})
    assert result.accepted is True
    assert result.provider_status == "ACCEPTED"
    # No amount, no settlement marker anywhere on the result.
    assert not hasattr(result, "settled")


def test_a_refusal_is_not_retryable():
    adapter = MpesaAdapter(
        config=config(),
        transport=transport_returning(
            400, {"errorCode": "400.002.02", "errorMessage": "Bad Request - Invalid Amount"}
        ),
    )
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})
    assert result.accepted is False
    assert result.failure_code == "400.002.02"
    assert result.retryable is False


def test_a_server_error_is_retryable():
    adapter = MpesaAdapter(config=config(), transport=transport_returning(503, {}))
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})
    assert result.accepted is False
    assert result.retryable is True


def test_a_transport_failure_is_retryable_and_collects_nothing():
    def _explode(*args):  # noqa: ARG001
        raise ConnectionError("network down")

    adapter = MpesaAdapter(config=config(), transport=_explode)
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})
    assert result.accepted is False
    assert result.failure_code == "PROVIDER_UNAVAILABLE"
    assert result.retryable is True


def test_fractional_amounts_are_refused_rather_than_rounded():
    """Rounding would collect a different sum from the one on the tender."""
    adapter = MpesaAdapter(config=config(), transport=transport_returning(200, {}))
    result = adapter.initiate(
        attempt=FakeAttempt(amount="100.50"), context={"phone_number": "0712345678"}
    )
    assert result.accepted is False
    assert result.failure_code == "AMOUNT_NOT_WHOLE"


def test_no_transport_configured_is_reported_as_unavailable():
    adapter = MpesaAdapter(config=config())
    result = adapter.initiate(attempt=FakeAttempt(), context={"phone_number": "0712345678"})
    assert result.accepted is False
    assert result.failure_code == "PROVIDER_UNAVAILABLE"


# -------------------------------------------------------------------- events


SUCCESS_CALLBACK = {
    "Body": {
        "stkCallback": {
            "MerchantRequestID": "29115-34620561-1",
            "CheckoutRequestID": "ws_CO_191220191020363925",
            "ResultCode": 0,
            "ResultDesc": "The service request is processed successfully.",
            "CallbackMetadata": {
                "Item": [
                    {"Name": "Amount", "Value": 1000},
                    {"Name": "MpesaReceiptNumber", "Value": "NLJ7RT61SV"},
                    {"Name": "PhoneNumber", "Value": 254712345678},
                    {"Name": "AccountReference", "Value": "REQ-abc123def4"},
                ]
            },
        }
    }
}

FAILED_CALLBACK = {
    "Body": {
        "stkCallback": {
            "CheckoutRequestID": "ws_CO_191220191020363925",
            "ResultCode": 1032,
            "ResultDesc": "Request cancelled by user",
        }
    }
}


def test_success_callback_is_flattened_to_the_neutral_shape():
    adapter = MpesaAdapter(config=config())
    event = adapter.parse_event(headers={}, payload=SUCCESS_CALLBACK)

    assert event.status == "SUCCEEDED"
    assert event.amount == Decimal("1000")
    assert event.provider_reference == "ws_CO_191220191020363925"
    assert event.currency == "KES"


def test_the_receipt_number_is_the_event_id():
    """Daraja's own unique id is what makes duplicate delivery detectable."""
    adapter = MpesaAdapter(config=config())
    event = adapter.parse_event(headers={}, payload=SUCCESS_CALLBACK)
    assert event.event_id == "NLJ7RT61SV"


def test_a_cancelled_payment_parses_as_failed_with_no_amount():
    adapter = MpesaAdapter(config=config())
    event = adapter.parse_event(headers={}, payload=FAILED_CALLBACK)
    assert event.status == "FAILED"
    assert event.amount is None
    assert "cancelled" in event.extra["result_desc"].lower()


def test_daraja_field_names_do_not_escape_the_adapter():
    """A provider quirk must not start driving payment decisions."""
    adapter = MpesaAdapter(config=config())
    event = adapter.parse_event(headers={}, payload=SUCCESS_CALLBACK)
    serialised = str(event)
    for daraja_field in ["stkCallback", "CallbackMetadata", "MerchantRequestID", "ResultCode"]:
        assert daraja_field not in serialised


# ------------------------------------------------------------ authentication


def test_an_unconfigured_callback_secret_accepts_nothing():
    """Without a secret we cannot tell a genuine callback from a forged one."""
    adapter = MpesaAdapter(config=config())
    assert adapter.authenticate_event(headers={"X-Callback-Token": "anything"}, payload={}) is False


def test_callback_token_must_match():
    cfg = config()
    object.__setattr__(cfg, "callback_secret", "the-real-token")
    adapter = MpesaAdapter(config=cfg)

    assert adapter.authenticate_event(headers={"X-Callback-Token": "the-real-token"}, payload={}) is True
    assert adapter.authenticate_event(headers={"X-Callback-Token": "forged"}, payload={}) is False
    assert adapter.authenticate_event(headers={}, payload={}) is False


# ------------------------------------------------------------------- registry


def test_mpesa_is_not_registered_until_verified():
    """It must not be selectable by configuration before it has been exercised
    against Safaricom."""
    from apps.prescription.payment_providers import ADAPTERS

    assert "MPESA" not in ADAPTERS


# --------------------------------------------------------------------- query


def test_query_returns_none_when_the_provider_is_unreachable():
    """Unknown is not failure: a till must not abandon a payment the customer
    actually completed."""

    def _explode(*args):  # noqa: ARG001
        raise TimeoutError("no route")

    adapter = MpesaAdapter(config=config(), transport=_explode)
    assert adapter.query_status(attempt=FakeAttempt()) is None


def test_query_reports_pending_while_the_customer_has_not_responded():
    adapter = MpesaAdapter(
        config=config(), transport=transport_returning(200, {"ResultCode": ""})
    )
    event = adapter.query_status(attempt=FakeAttempt())
    assert event is not None
    assert event.status == "PENDING"
    assert event.amount is None
