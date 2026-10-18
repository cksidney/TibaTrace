"""Server-only tenant payment configuration. Secrets are environment references.

TIBATRACE_CHECKOUT_CONNECTIONS is keyed by tenant UUID, with optional branch
overrides keyed by tenant UUID/branch UUID.
Only sanitized readiness metadata is sent to a till. Activation requires an
explicit validated flag after the operator has supplied provider evidence.
"""

import json
import os
import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError


def connection(*, tenant, branch, provider):
    try:
        all_config = json.loads(os.environ.get("TIBATRACE_CHECKOUT_CONNECTIONS", "{}"))
        tenant_config = all_config.get(str(tenant.pk), {}).get(provider, {})
        branch_config = all_config.get(f"{tenant.pk}/{branch.pk}", {}).get(provider, {})
    except (ValueError, AttributeError):
        raise ValidationError("Checkout connection configuration is invalid.") from None
    if not isinstance(tenant_config, dict) or not isinstance(branch_config, dict):
        raise ValidationError("Checkout connection configuration is invalid.")
    # Provider credentials and defaults are tenant-scoped. A branch may override
    # non-secret device metadata or use a distinct credential reference when its
    # acquirer account is configured separately.
    return {**tenant_config, **branch_config}


def secret(config, name):
    reference = config.get(name + "_env", "")
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", reference):
        raise ValidationError(f"Configure the server credential reference for {name}.")
    value = os.environ.get(reference, "")
    if not value:
        raise ValidationError(f"The server credential for {name} is unavailable.")
    return value


def _card_adapter_code(config):
    code = str(config.get("provider_code", "")).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        raise ValidationError("Configure a registered card terminal provider code.")
    if code in {"MANUAL", "FAKE", "MPESA"}:
        raise ValidationError("The card terminal provider code is reserved.")
    return code


def mpesa_adapter(*, tenant, branch):
    from apps.prescription.payment_providers_mpesa import DarajaTransport, MpesaAdapter, MpesaConfig

    cfg = connection(tenant=tenant, branch=branch, provider="MPESA")
    if cfg.get("enabled") is not True or cfg.get("validated") is not True:
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


def card_terminal_adapter(*, tenant, branch):
    """Resolve a tenant/branch card adapter without returning its secrets.

    Provider code and non-secret terminal metadata are deployment config;
    secret material is resolved from environment references immediately before
    adapter construction. The adapter itself must be installed in the server
    registry, so configuration cannot activate arbitrary code.
    """
    from apps.prescription.payment_providers import get_adapter

    cfg = connection(tenant=tenant, branch=branch, provider="CARD")
    if cfg.get("enabled") is not True or cfg.get("validated") is not True:
        raise ValidationError("Card terminal integration is not enabled and validated for this branch.")
    code = _card_adapter_code(cfg)
    credentials_env = cfg.get("credentials_env", {})
    if not isinstance(credentials_env, dict):
        raise ValidationError("Card terminal credential references must be a server-side mapping.")
    credentials = {}
    for name, reference in credentials_env.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(name)):
            raise ValidationError("Card terminal credential names must be lowercase identifiers.")
        credentials[name] = secret({f"{name}_env": reference}, name)
    adapter_config = {
        key: value
        for key, value in cfg.items()
        if key != "credentials_env" and not key.endswith("_env")
    }
    adapter = get_adapter(code, tenant=tenant, branch=branch, config=adapter_config, credentials=credentials)
    required_methods = (
        "validate_configuration",
        "initiate",
        "query_status",
        "authenticate_event",
        "parse_event",
    )
    if any(not callable(getattr(adapter, method, None)) for method in required_methods):
        raise ValidationError("The installed card adapter does not implement the payment provider contract.")
    if str(getattr(adapter, "provider_code", "")).upper() != code:
        raise ValidationError("The installed card adapter code does not match tenant configuration.")
    adapter.validate_configuration(tenant=tenant, branch=branch)
    return code, adapter, adapter_config


def provider_adapter(*, tenant, branch, provider_code):
    """Resolve an adapter from the source tenant's current approved config."""
    from apps.prescription.payment_providers import normalize_provider_code

    code = normalize_provider_code(provider_code)
    if code == "MPESA":
        return mpesa_adapter(tenant=tenant, branch=branch)
    configured_code, adapter, _config = card_terminal_adapter(tenant=tenant, branch=branch)
    if code != configured_code:
        raise ValidationError("The payment attempt provider does not match the configured branch integration.")
    return adapter


def card_manual_fallback_allowed(*, tenant, branch):
    """Manual approval is only a fallback when the tenant explicitly allows it."""
    cfg = connection(tenant=tenant, branch=branch, provider="CARD")
    return cfg.get("manual_fallback") is True


def require_external_card_refund(*, tenant, branch, provider_code):
    """An integrated charge needs a verified original-provider return process."""
    if provider_code == "MANUAL":
        return
    cfg = connection(tenant=tenant, branch=branch, provider="CARD")
    if (
        str(cfg.get("provider_code", "")).strip().upper() != provider_code
        or cfg.get("validated") is not True
        or cfg.get("manual_refunds") is not True
    ):
        raise ValidationError(
            "This integrated card payment requires a validated original-provider refund procedure. "
            "A manual reference cannot substitute for provider reversal evidence."
        )


def vscu_config(*, tenant, branch):
    config = connection(tenant=tenant, branch=branch, provider="VSCU")
    if config.get("enabled") is not True or config.get("validated") is not True:
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
        mpesa = {
            "type": "MPESA", "label": "M-PESA", "available": True, "blocker": "",
            "integration_mode": "INTEGRATED", "integration_status": "READY", "provider_code": "MPESA",
        }
    except (ValidationError, ValueError):
        mpesa = {
            "type": "MPESA",
            "label": "M-PESA",
            "available": False,
            "blocker": "Daraja API setup and validation required",
            "integration_mode": "UNAVAILABLE",
            "integration_status": "NOT_READY",
            "provider_code": "MPESA",
        }
    try:
        card_cfg = connection(tenant=tenant, branch=branch, provider="CARD")
    except ValidationError:
        return [
            {"type": "CASH", "label": "Cash", "available": True, "blocker": ""},
            {"type": "CARD", "label": "Card", "available": False,
             "blocker": "Server payment configuration requires review.",
             "integration_mode": "UNAVAILABLE", "integration_status": "CONFIGURATION_ERROR", "provider_code": ""},
            mpesa,
        ]
    card_status = "NOT_CONFIGURED"
    card_provider = ""
    try:
        card_provider, _adapter, _safe_config = card_terminal_adapter(tenant=tenant, branch=branch)
        card_status = "READY"
        card = {
            "type": "CARD", "label": str(card_cfg.get("label") or f"Card · {card_provider}"),
            "available": True, "blocker": "", "integration_mode": "INTEGRATED",
            "integration_status": card_status, "provider_code": card_provider,
        }
    except Exception:  # noqa: BLE001 - a broken provider must not break checkout status reads
        if card_cfg.get("enabled") and not card_cfg.get("validated"):
            card_status = "VALIDATION_REQUIRED"
        elif card_cfg.get("enabled") and card_cfg.get("validated"):
            try:
                card_provider = _card_adapter_code(card_cfg)
                from apps.prescription.payment_providers import ADAPTERS
                card_status = "ADAPTER_NOT_INSTALLED" if card_provider not in ADAPTERS else "CONFIGURATION_ERROR"
            except ValidationError:
                card_status = "CONFIGURATION_ERROR"
        manual_fallback = card_cfg.get("manual_fallback") is True
        integrated_setup = bool(card_cfg.get("enabled"))
        card = {
            "type": "CARD", "label": "Card · external terminal approval",
            "available": not integrated_setup or manual_fallback,
            "blocker": (
                "Use the tenant's external terminal and enter its approval reference."
                if not integrated_setup or manual_fallback
                else "The configured card integration is not ready. Complete provider setup or enable an approved manual fallback."
            ),
            "integration_mode": "MANUAL", "integration_status": card_status,
            "provider_code": card_provider or "MANUAL",
        }
    return [
        {"type": "CASH", "label": "Cash", "available": True, "blocker": ""},
        card,
        mpesa,
    ]
