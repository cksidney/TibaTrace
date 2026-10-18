import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.prescription.payment_connections import (
    card_terminal_adapter,
    connection,
    payment_options,
    require_external_card_refund,
)
from apps.prescription.payment_providers import ADAPTERS


class StubCardAdapter:
    provider_code = "TEST_ACQUIRER"

    def __init__(self, *, tenant, branch, config, credentials):
        self.tenant = tenant
        self.branch = branch
        self.config = config
        self.credentials = credentials

    def validate_configuration(self, *, tenant, branch=None):
        assert tenant.pk == self.tenant.pk
        assert branch.pk == self.branch.pk

    def initiate(self, *, attempt, context):  # noqa: ARG002
        raise NotImplementedError

    def query_status(self, *, attempt):  # noqa: ARG002
        return None

    def authenticate_event(self, *, headers, payload, raw_body=b""):  # noqa: ARG002
        return False

    def parse_event(self, *, headers, payload):  # noqa: ARG002
        raise NotImplementedError


def tenant_branch(tenant_id, branch_id):
    return SimpleNamespace(pk=tenant_id), SimpleNamespace(pk=branch_id)


def test_connection_uses_tenant_defaults_with_branch_override_and_hides_credentials(monkeypatch):
    tenant, branch = tenant_branch("tenant-one", "branch-one")
    other_tenant, other_branch = tenant_branch("tenant-two", "branch-two")
    secret_value = "tenant-one-sensitive-api-key"
    monkeypatch.setenv("TIBATRACE_CARD_KEY_ONE", secret_value)
    monkeypatch.setenv(
        "TIBATRACE_CHECKOUT_CONNECTIONS",
        json.dumps(
            {
                "tenant-one": {
                    "CARD": {
                        "enabled": True,
                        "validated": True,
                        "provider_code": "TEST_ACQUIRER",
                        "label": "Tenant card terminal",
                        "terminal_id": "TENANT-TERMINAL",
                        "credentials_env": {"api_key": "TIBATRACE_CARD_KEY_ONE"},
                    }
                },
                "tenant-one/branch-one": {"CARD": {"terminal_id": "BRANCH-TERMINAL"}},
            }
        ),
    )
    captured = {}

    def factory(**values):
        captured.update(values)
        return StubCardAdapter(**values)

    monkeypatch.setitem(ADAPTERS, "TEST_ACQUIRER", factory)

    code, adapter, safe_config = card_terminal_adapter(tenant=tenant, branch=branch)
    assert code == "TEST_ACQUIRER"
    assert adapter.config["terminal_id"] == "BRANCH-TERMINAL"
    assert "credentials_env" not in safe_config
    assert captured["credentials"] == {"api_key": secret_value}
    assert connection(tenant=other_tenant, branch=other_branch, provider="CARD") == {}
    serialized_options = json.dumps(payment_options(tenant=tenant, branch=branch))
    assert secret_value not in serialized_options
    assert "credentials_env" not in serialized_options


def test_card_stays_manual_when_no_adapter_is_installed_and_cannot_use_unregistered_code(monkeypatch):
    tenant, branch = tenant_branch("tenant-three", "branch-three")
    monkeypatch.setenv(
        "TIBATRACE_CHECKOUT_CONNECTIONS",
        json.dumps(
            {
                "tenant-three": {
                    "CARD": {
                        "enabled": True,
                        "validated": True,
                        "provider_code": "MISSING_ACQUIRER",
                    }
                }
            }
        ),
    )

    card = next(option for option in payment_options(tenant=tenant, branch=branch) if option["type"] == "CARD")
    assert card["available"] is False
    assert card["integration_status"] == "ADAPTER_NOT_INSTALLED"
    with pytest.raises(ValueError, match="No payment adapter is registered"):
        card_terminal_adapter(tenant=tenant, branch=branch)


def test_manual_fallback_requires_explicit_tenant_setting(monkeypatch):
    tenant, branch = tenant_branch("tenant-four", "branch-four")
    monkeypatch.setenv(
        "TIBATRACE_CHECKOUT_CONNECTIONS",
        json.dumps(
            {
                "tenant-four": {
                    "CARD": {
                        "enabled": True,
                        "validated": True,
                        "provider_code": "MISSING_ACQUIRER",
                        "manual_fallback": True,
                    }
                }
            }
        ),
    )

    card = next(option for option in payment_options(tenant=tenant, branch=branch) if option["type"] == "CARD")
    assert card["available"] is True
    assert card["integration_mode"] == "MANUAL"


@pytest.mark.parametrize("broken_config", ["not-json", "[]", '{"tenant-broken": {"CARD": []}}'])
def test_invalid_integration_config_disables_providers_without_hiding_cash(monkeypatch, broken_config):
    tenant, branch = tenant_branch("tenant-broken", "branch-broken")
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", broken_config)
    options = {item["type"]: item for item in payment_options(tenant=tenant, branch=branch)}
    assert options["CASH"]["available"] is True
    assert options["CARD"]["available"] is False
    assert options["MPESA"]["available"] is False


def test_integrated_card_refund_requires_an_explicit_validated_tenant_procedure(monkeypatch):
    tenant, branch = tenant_branch("tenant-refund", "branch-refund")
    config = {"tenant-refund": {"CARD": {"provider_code": "TEST_ACQUIRER", "validated": True}}}
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", json.dumps(config))
    with pytest.raises(ValidationError, match="refund procedure"):
        require_external_card_refund(tenant=tenant, branch=branch, provider_code="TEST_ACQUIRER")
    config["tenant-refund"]["CARD"]["manual_refunds"] = True
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", json.dumps(config))
    require_external_card_refund(tenant=tenant, branch=branch, provider_code="TEST_ACQUIRER")
    with pytest.raises(ValidationError, match="refund procedure"):
        require_external_card_refund(tenant=tenant, branch=branch, provider_code="OTHER_ACQUIRER")
