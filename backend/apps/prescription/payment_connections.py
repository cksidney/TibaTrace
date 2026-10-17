"""Server-only branch payment configuration. Secrets are environment references.

TIBATRACE_CHECKOUT_CONNECTIONS contains JSON keyed by tenant UUID/branch UUID.
No config value or credential is sent to a till. Production activation requires
an explicit validated flag after the operator has supplied provider evidence.
"""

import json
import os
import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError


def connection(*, tenant, branch, provider):
    try:
        all_config = json.loads(os.environ.get("TIBATRACE_CHECKOUT_CONNECTIONS", "{}"))
        config = all_config.get(f"{tenant.pk}/{branch.pk}", {}).get(provider, {})
    except (ValueError, AttributeError):
        raise ValidationError("Checkout connection configuration is invalid.") from None
    return config if isinstance(config, dict) else {}


def secret(config, name):
    reference = config.get(name + "_env", "")
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", reference):
        raise ValidationError(f"Configure the server credential reference for {name}.")
    value = os.environ.get(reference, "")
    if not value:
        raise ValidationError(f"The server credential for {name} is unavailable.")
    return value


def mpesa_adapter(*, tenant, branch):
    from apps.prescription.payment_providers_mpesa import DarajaTransport, MpesaAdapter, MpesaConfig

    cfg = connection(tenant=tenant, branch=branch, provider="MPESA")
    if not cfg.get("enabled") or not cfg.get("validated"):
        raise ValidationError("M-PESA awaits supplied Daraja credentials and provider validation.")
    config = MpesaConfig(
        consumer_key=secret(cfg, "consumer_key"),
        consumer_secret=secret(cfg, "consumer_secret"),
        short_code=str(cfg.get("short_code", "")),
        passkey=secret(cfg, "passkey"),
        callback_url=str(cfg.get("callback_url", "")),
        environment=str(cfg.get("environment", "sandbox")),
    )
    return MpesaAdapter(config=config, transport=DarajaTransport(config))


def vscu_config(*, tenant, branch):
    config = connection(tenant=tenant, branch=branch, provider="VSCU")
    if not config.get("enabled") or not config.get("validated"):
        raise ValidationError("VSCU awaits the registered device, item mappings and integration validation.")
    url = urlparse(config.get("base_url", ""))
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValidationError("Configure a valid server VSCU endpoint.")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValidationError("Remote VSCU connections require HTTPS.")
    if not config.get("tin") or not config.get("bhf_id"):
        raise ValidationError("VSCU taxpayer and branch registration are required.")
    return config


def payment_options(*, tenant, branch):
    try:
        mpesa_adapter(tenant=tenant, branch=branch)
        mpesa = {"type": "MPESA", "label": "M-PESA", "available": True, "blocker": ""}
    except (ValidationError, ValueError):
        mpesa = {
            "type": "MPESA",
            "label": "M-PESA",
            "available": False,
            "blocker": "Daraja API setup and validation required",
        }
    return [
        {"type": "CASH", "label": "Cash", "available": True, "blocker": ""},
        {
            "type": "CARD",
            "label": "Card · terminal approval",
            "available": True,
            "blocker": "Record the approval reference from the external terminal",
        },
        mpesa,
    ]
