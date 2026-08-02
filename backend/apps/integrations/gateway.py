"""National Integration Gateway.

Authoritative Gateway base class for national health & regulatory provider adapters.

All integrations (DHA HIE, DHA HWR, PPB Premises, PPB Products, PPB Alerts, GS1, SHA, Insurance)
inherit from NationalIntegrationGateway to ensure unified governance:
  - Provider registration & activation gating
  - Encrypted credential references
  - OAuth token lifecycle & TLS host allow-listing
  - Retry queues with exponential backoff & full jitter
  - Process-local circuit breaking
  - Dead-lettering & manual replay audit
  - Role-scoped operational notifications
  - Health snapshot monitoring & evidence capture
  - Platform Owner approval enforcement
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from django.core.exceptions import PermissionDenied

from apps.audit.service import log_audit
from apps.integrations.models import (
    ProviderConfiguration,
    ProviderEnvironment,
)
from apps.integrations.reliability import (
    get_circuit_breaker,
)

logger = logging.getLogger(__name__)


class NationalIntegrationGateway(ABC):
    """Abstract base class for all national health and regulatory integration adapters."""

    def __init__(
        self,
        provider_type: str,
        environment: str = ProviderEnvironment.SANDBOX,
        mode: str = "MANUAL_GOVERNED",
    ) -> None:
        self.provider_type = provider_type
        self.environment = environment
        self.mode = mode
        self.circuit_breaker = get_circuit_breaker(provider_type)

    @property
    def configuration(self) -> ProviderConfiguration | None:
        """Fetch the current database configuration for this provider."""
        return ProviderConfiguration.all_objects.filter(
            provider_type=self.provider_type,
            environment=self.environment,
        ).first()

    @property
    def is_operational(self) -> bool:
        """Check if the provider is fully activated by the Platform Owner."""
        cfg = self.configuration
        return bool(cfg and cfg.is_operational)

    @property
    def truth_label(self) -> str:
        cfg = self.configuration
        return cfg.truth_label if cfg else "ADAPTER_SCAFFOLDED_NOT_CONNECTED"

    def verify_activation_gate(self) -> None:
        """Fail-closed check: raise PermissionDenied if provider is not ACTIVE."""
        if not self.is_operational:
            raise PermissionDenied(
                f"Integration '{self.provider_type}' ({self.environment}) is not active. "
                f"Truth label: {self.truth_label}. Platform Owner activation required."
            )

    @abstractmethod
    def send_payload(self, message_type: str, payload: dict, tenant_id: object | None = None) -> dict[str, Any]:
        """Dispatch payload to provider endpoint.

        Must enforce TLS host allow-listing and record attempt metrics.
        """
        pass

    def record_execution_evidence(
        self,
        *,
        action: str,
        success: bool,
        tenant_id: object | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Log immutable audit evidence for provider execution."""
        log_audit(
            tenant_id=tenant_id,
            action=f"PROVIDER_{self.provider_type}_{action}",
            model_name="NationalIntegrationGateway",
            object_id=self.provider_type,
            outcome="SUCCESS" if success else "FAILURE",
            metadata={
                "provider_type": self.provider_type,
                "environment": self.environment,
                "mode": self.mode,
                "truth_label": self.truth_label,
                **(metadata or {}),
            },
        )
