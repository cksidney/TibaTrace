"""Run periodically via the deployment scheduler; no clinical data is printed."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.dha_catalogue import OPERATIONS
from apps.integrations.dha_models import DhaExchange
from apps.integrations.dha_workflows import execute


class Command(BaseCommand):
    help = "Process bounded DHA retries; quarantine interrupted mutations for reconciliation."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        now = timezone.now()
        expired = DhaExchange.all_objects.filter(state="IN_FLIGHT", lease_expires_at__lte=now)
        for row in expired:
            is_read = OPERATIONS[row.operation].method == "GET"
            DhaExchange.all_objects.filter(pk=row.pk, tenant_id=row.tenant_id, state="IN_FLIGHT", lease_expires_at__lte=now).update(
                state="RETRY" if is_read and row.attempts < 5 else "UNCERTAIN", next_attempt_at=now,
                error_code="WORKER_INTERRUPTED", lease_expires_at=None)
        rows = DhaExchange.all_objects.filter(state__in=["PENDING", "RETRY"]).order_by("created_at")[:max(1, min(options["limit"], 200))]
        processed = 0
        for row in rows:
            if not row.next_attempt_at or row.next_attempt_at <= now:
                execute(row)
                processed += 1
        self.stdout.write(f"DHA exchange commands examined: {processed}")
