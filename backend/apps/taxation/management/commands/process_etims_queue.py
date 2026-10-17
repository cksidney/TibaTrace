"""Management command: process_etims_queue.

Flushes pending/failed eTIMS fiscalization queue to KRA VSCU.

Usage:
    python manage.py process_etims_queue [--limit 50] [--tenant <tenant_id>]
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.taxation.models import FiscalReceipt, TenantEtimsProfile
from apps.taxation.services import FiscalizationPipeline

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process pending KRA eTIMS submissions in the durable retry queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of pending receipts to process (default: 50).",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Filter queue processing to a single tenant UUID.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        tenant_id = options["tenant"]
        now = timezone.now()

        qs = FiscalReceipt.all_objects.filter(
            submission_status__in=[
                FiscalReceipt.SubmissionStatus.PENDING,
                FiscalReceipt.SubmissionStatus.FAILED,
            ]
        )
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        # Include items where next_retry_at is null or due
        due_qs = qs.filter(
            models_due := (
                models_q := FiscalReceipt.all_objects.filter(next_retry_at__isnull=True)
                | FiscalReceipt.all_objects.filter(next_retry_at__lte=now)
            )
        )
        # Simplify filter
        pending_receipts = [
            r for r in qs.order_by("created_at")[:limit]
            if r.next_retry_at is None or r.next_retry_at <= now
        ]

        self.stdout.write(f"Found {len(pending_receipts)} due fiscal receipt(s) in queue.")

        processed = 0
        succeeded = 0
        failed = 0

        for receipt in pending_receipts:
            profile = TenantEtimsProfile.all_objects.filter(tenant_id=receipt.tenant_id).first()
            if not profile or not profile.is_enabled or not profile.is_configured:
                continue

            processed += 1
            success = FiscalizationPipeline.transmit_to_vscu(receipt, profile)
            if success:
                succeeded += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Receipt #{receipt.invoice_number} (Tenant: {receipt.tenant_id}) submitted successfully."
                    )
                )
            else:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Receipt #{receipt.invoice_number} transmission failed: {receipt.last_error}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Queue processing completed: {processed} processed, {succeeded} succeeded, {failed} failed."
            )
        )
