"""Credential references, rotating encryption keys and approved HTTPS destinations."""
import json
import os
import re
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ValidationError


def secret(reference):
    if not isinstance(reference, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", reference):
        raise ValidationError("Use an environment credential reference, never its value.")
    value = os.environ.get(reference, "")
    if not value or any(ord(c) < 32 for c in value):
        raise ValidationError("A required DHA credential reference is unresolved.")
    return value


def cipher():
    # Ordered keys: first encrypts; remaining keys decrypt historical journals.
    try:
        keys = json.loads(os.environ.get("TIBATRACE_DHA_DATA_KEYS", "[]"))
        if not isinstance(keys, list) or not keys:
            raise ValueError
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("DHA journal encryption keys are not configured.") from None


def protect(connection, value):
    return cipher().encrypt(json.dumps({"connection": str(connection.pk), "value": value}, sort_keys=True).encode()).decode()


def reveal(connection, value):
    try:
        body = json.loads(cipher().decrypt(value.encode()))
        if body["connection"] != str(connection.pk):
            raise ValueError
        return body["value"]
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise ValidationError("DHA protected data cannot be opened for this connection.") from None


def approved_url(config, path):
    raw = config.get("base_url", "")
    if not isinstance(raw, str) or any(ord(c) < 33 for c in raw):
        raise ValidationError("A plain HTTPS DHA base URL is required.")
    base = raw.rstrip("/")
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError:
        raise ValidationError("The DHA endpoint URL is invalid.") from None
    hosts = [h.strip().lower() for h in os.environ.get("TIBATRACE_DHA_ALLOWED_HOSTS", "ilm-dev.dha.go.ke").split(",") if h.strip()]
    allowed = config.get("allowed_hosts", [])
    if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.hostname not in allowed
            or parsed.username or parsed.password or parsed.query or parsed.fragment or port not in (None, 443)
            or not parsed.path.endswith("/api/v1") or ".." in parsed.path or "//" in parsed.path
            or not re.fullmatch(r"/[A-Za-z0-9_/-]+", parsed.path)
            or not path.startswith("/") or ".." in path or "//" in path or "?" in path or "#" in path):
        raise ValidationError("Use an approved HTTPS DHA /api/v1 base and relative operation path.")
    return base + path


CONFIG_FIELDS = {"base_url", "allowed_hosts", "client_id_ref", "client_secret_ref", "callback_secret_ref", "facility_id",
    "hie_tenant_id", "claims_enabled", "practitioner_map", "prescriber_map", "product_map",
    "terminology_owner", "terminology_source", "callback_hie_secret_ref", "unit_map", "remittance_paths"}


def validate_config(config):
    if not isinstance(config, dict) or set(config) - CONFIG_FIELDS:
        raise ValidationError("Unsupported DHA configuration fields; store credential references only.")
    if not isinstance(config.get("allowed_hosts"), list) or any(not isinstance(h, str) for h in config["allowed_hosts"]):
        raise ValidationError("allowed_hosts must be a list of approved hostnames.")
    approved_url(config, "/tenants/token")
    for key in ("client_id_ref", "client_secret_ref", "callback_secret_ref"):
        ref = config.get(key, "")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", ref):
            raise ValidationError(f"{key} requires a credential reference name.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", config.get("facility_id", "")):
        raise ValidationError("The branch's verified Facility Registry code is required.")
    mappings = config.get("practitioner_map", {})
    if not isinstance(mappings, dict) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", v) for v in mappings.values()):
        raise ValidationError("Practitioner mappings require local user IDs and verified PUID values.")
    import uuid
    try:
        for local in mappings:
            if not isinstance(local, str) or not local.isdigit():
                raise ValueError
        for key in ("prescriber_map", "product_map"):
            mapping = config.get(key, {})
            if not isinstance(mapping, dict):
                raise ValueError
            for external, local in mapping.items():
                if not external or len(external) > 255:
                    raise ValueError
                uuid.UUID(local)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Identity and product mappings require valid local UUIDs.") from None
    if not isinstance(config.get("claims_enabled", False), bool):
        raise ValidationError("claims_enabled must be true or false.")
    routes = config.get("remittance_paths", {})
    if not isinstance(routes, dict) or set(routes) - {"remittances", "remittance_claims"}:
        raise ValidationError("Use only the assigned remittance contract route keys.")
    for route in routes.values():
        if not isinstance(route, str) or not re.fullmatch(r"/[A-Za-z0-9_/-]+", route) or "//" in route:
            raise ValidationError("Remittance contracts require a plain relative path without query parameters.")
    units = config.get("unit_map", {})
    if not isinstance(units, dict) or any(not isinstance(v, dict) or not isinstance(v.get("system"), str)
            or not isinstance(v.get("code"), str) or not v["system"] or not v["code"] for v in units.values()):
        raise ValidationError("Unit mappings require a coding system and code for every mapped local unit.")


def readiness(connection):
    blockers = []
    try:
        environments = json.loads(os.environ.get("TIBATRACE_DHA_ENVIRONMENT_BASES", json.dumps({
            "SANDBOX": ["https://ilm-dev.dha.go.ke/uat-middleware/api/v1"], "PRODUCTION": []})))
        approved = environments.get(connection.environment, [])
        if not isinstance(approved, list) or connection.configuration.get("base_url", "").rstrip("/") not in approved:
            blockers.append(f"Configure the approved {connection.environment.lower()} API base on the server.")
    except (ValueError, TypeError, AttributeError):
        blockers.append("The DHA environment base policy requires review.")
    try:
        validate_config(connection.configuration)
    except ValidationError as exc:
        blockers.extend(exc.messages)
    for key in ("client_id_ref", "client_secret_ref", "callback_secret_ref"):
        try:
            value = secret(connection.configuration.get(key))
            if key == "callback_secret_ref" and len(value) < 32:
                raise ValidationError("Callback credentials need at least 32 characters.")
        except ValidationError:
            blockers.append(f"Supply {key} through the server secrets manager.")
    try:
        cipher()
    except ValidationError:
        blockers.append("Configure DHA journal encryption keys.")
    if connection.validated_revision != connection.revision:
        blockers.append("Validate connectivity for this configuration revision.")
    if connection.branch.status != "ACTIVE":
        blockers.append("The branch is inactive.")
    if not connection.tenant.may_operate:
        blockers.append("The tenant is not operational.")
    from apps.integrations.models import ProviderConfiguration
    if ProviderConfiguration.all_objects.filter(provider_type="DHA_HIE", environment=connection.environment,
            activation_state__in=["SUSPENDED", "REVOKED", "DECOMMISSIONED"]).exists():
        blockers.append("The platform DHA provider kill switch is engaged.")
    return {"ready": not blockers, "blockers": blockers, "state": connection.state,
            "connected": connection.state in {"SANDBOX", "ACTIVE"} and not blockers}
