"""Tenant-scoped prescription feed adapter seam; no connector is enabled by default.

Connectors return the normalized source references below. Explicit tenant maps
resolve those references to governed records; source claims never verify an RX.
"""
import json
import os
import re

from django.core.exceptions import ValidationError

from apps.prescription.payment_connections import secret

FEED_ADAPTERS = {}
PROVIDERS = ("HOSPITAL_EMR", "DHA")


def register_feed_adapter(code, factory):
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code) or not callable(factory) or code in FEED_ADAPTERS:
        raise ValueError("A unique installed feed adapter code and callable factory are required.")
    FEED_ADAPTERS[code] = factory


def feed_connection(*, tenant, provider):
    if provider not in PROVIDERS:
        raise ValidationError("Unsupported prescription feed.")
    try:
        config = json.loads(os.environ.get("TIBATRACE_RX_CONNECTIONS", "{}")).get(str(tenant.pk), {}).get(provider, {})
        if not isinstance(config, dict):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValidationError("Prescription feed configuration requires review.") from None
    if config.get("enabled") is not True or config.get("validated") is not True:
        raise ValidationError("This tenant's prescription feed is not enabled and validated.")
    return config


def feed_adapter(*, tenant, provider, branch=None, actor=None):
    if provider == "DHA" and branch is not None and actor is not None:
        from apps.integrations.dha_models import DhaConnection
        if DhaConnection.all_objects.filter(tenant=tenant, branch=branch).exists():
            from apps.integrations.dha_rx import tenant_feed
            return tenant_feed(tenant, branch, actor)
    config = feed_connection(tenant=tenant, provider=provider)
    if any(not isinstance(config.get(name), dict) or not config[name] for name in ("patient_map", "prescriber_map", "product_map")):
        raise ValidationError("Tenant patient, prescriber and product mappings are required before feed activation.")
    code = config.get("adapter_code")
    factory = FEED_ADAPTERS.get(code) if isinstance(code, str) else None
    if not factory:
        raise ValidationError("The tenant's prescription feed connector is not installed.")
    refs = config.get("credentials_env", {})
    if not isinstance(refs, dict) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) for key in refs):
        raise ValidationError("Feed credential references are invalid.")
    credentials = {name: secret({f"{name}_env": reference}, name) for name, reference in refs.items()}
    safe_config = {key: value for key, value in config.items() if key != "credentials_env" and not key.endswith("_env")}
    try:
        adapter = factory(tenant=tenant, provider=provider, config=safe_config, credentials=credentials)
        if not callable(getattr(adapter, "validate_configuration", None)) or not callable(getattr(adapter, "fetch_prescription", None)):
            raise ValueError("Incomplete adapter")
        adapter.validate_configuration(tenant=tenant)
    except Exception:
        # Connector exceptions may contain endpoint URLs or credentials.
        raise ValidationError("The tenant's prescription connector configuration requires review.") from None
    return adapter, safe_config


def feed_readiness(tenant, branch=None, actor=None):
    result = []
    for provider in PROVIDERS:
        try:
            feed_adapter(tenant=tenant, provider=provider, branch=branch, actor=actor)
            ready = True
        except Exception:  # a connector configuration error must not break manual intake
            ready = False
        result.append({"code": provider, "available": ready,
                       "message": "Ready for reviewed import" if ready else "Tenant connector, credentials and validation required"})
    return result
