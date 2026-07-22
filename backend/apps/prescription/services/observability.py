from typing import Any, Dict

from apps.prescription.models import DeadLetterQueue, IntegrationOutbox, ProviderConfiguration
from apps.prescription.providers.base import AdapterFactory


class ObservabilityService:
    """
    Aggregates operational telemetry for the National Prescription Domain.
    Used by dashboarding tools to monitor inter-provider connectivity.
    """

    @staticmethod
    def get_provider_health(*, tenant_id) -> Dict[str, Any]:
        if not tenant_id:
            raise ValueError("Provider health requires an explicit tenant.")
        health_metrics = {}
        providers = ProviderConfiguration.all_objects.filter(tenant_id=tenant_id, is_active=True)

        for provider in providers:
            adapter = AdapterFactory.get_adapter(provider.provider_code)
            outbox_depth = IntegrationOutbox.all_objects.filter(
                tenant_id=tenant_id, provider_code=provider.provider_code, status="PENDING"
            ).count()
            dlq_depth = DeadLetterQueue.all_objects.filter(
                tenant_id=tenant_id, outbox_item__provider_code=provider.provider_code
            ).count()

            health_metrics[provider.provider_code] = {
                "configured": True,
                "adapter_reachable": bool(adapter.check_health()),
                "queue_depth": outbox_depth,
                "dead_letter_depth": dlq_depth,
            }

        return health_metrics
