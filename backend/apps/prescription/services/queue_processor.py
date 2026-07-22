import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.prescription.models import DeadLetterQueue, IntegrationOutbox, ProviderConfiguration
from apps.prescription.providers.base import AdapterFactory
from apps.prescription.services.compliance import ComplianceService

logger = logging.getLogger(__name__)

class IntegrationQueueProcessor:
    """
    Asynchronous Integration Queue Processor.
    Handles reliable delivery, retries, and dead-letter routing natively.
    """

    @staticmethod
    @transaction.atomic
    def process_pending_messages(*, tenant_id, limit: int = 100):
        """
        Pulls PENDING messages or those past their next_retry_at threshold.
        """
        if not tenant_id:
            raise ValueError("Integration processing requires an explicit tenant.")
        now = timezone.now()
        messages_to_process = list(
            IntegrationOutbox.all_objects.select_for_update()
            .filter(tenant_id=tenant_id)
            .filter(Q(status="PENDING") | Q(status="RETRYING", next_retry_at__lte=now))
            .order_by("created_at")[: max(1, min(int(limit), 500))]
        )

        for msg in messages_to_process:
            IntegrationQueueProcessor._process_single_message(msg, tenant_id=tenant_id)
        return len(messages_to_process)

    @staticmethod
    def _process_single_message(msg: IntegrationOutbox, *, tenant_id):
        if not tenant_id or str(msg.tenant_id) != str(tenant_id):
            raise ValueError("Integration message is outside the supplied tenant.")
        try:
            config = ProviderConfiguration.all_objects.get(
                tenant_id=tenant_id, provider_code=msg.provider_code
            )
            if not config.is_active:
                raise ValueError("Provider configuration is inactive.")

            adapter = AdapterFactory.get_adapter(msg.provider_code)

            # Enforce minimum disclosure policies
            clean_payload = ComplianceService.enforce_minimum_disclosure(msg.payload, msg.provider_code)

            success = False
            if msg.event_type == "SUBMIT_DISPENSE":
                success = adapter.submit_dispense(clean_payload)
            elif msg.event_type == "CANCEL_DISPENSE":
                success = adapter.cancel_dispense(clean_payload.get('reference', ''), clean_payload.get('reason', ''))
            else:
                raise ValueError("Unsupported provider event type.")

            if success:
                msg.status = "DELIVERED"
                msg.save()
            else:
                raise RuntimeError("Provider rejected the payload or returned an error.")

        except Exception as e:
            msg.retry_count += 1
            msg.last_error = str(e)

            # Simple exponential backoff policy (up to 3 retries)
            if msg.retry_count > 3:
                msg.status = "DEAD_LETTER"
                msg.save(update_fields=["status", "retry_count", "last_error", "updated_at"])
                DeadLetterQueue.all_objects.create(
                    tenant_id=tenant_id,
                    outbox_item=msg,
                    reason=f"Exceeded max retries. Last error: {str(e)}"
                )
            else:
                msg.status = "RETRYING"
                msg.next_retry_at = timezone.now() + timedelta(minutes=(5 ** msg.retry_count))
                msg.save(
                    update_fields=["status", "retry_count", "last_error", "next_retry_at", "updated_at"]
                )
