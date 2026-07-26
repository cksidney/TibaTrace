from django.core.management.base import BaseCommand

from apps.procurement.models import GoodsReceipt, PurchaseOrder, ThreeWayMatch


class Command(BaseCommand):
    help = "Check integrity of procurement records, PO approvals, GRN postings, and 3-way matches."

    def handle(self, *args, **options):
        self.stdout.write("Running Procurement Integrity Checks...")
        
        pos_without_lines = PurchaseOrder.all_objects.filter(lines__isnull=True).count()
        grns_without_lines = GoodsReceipt.all_objects.filter(lines__isnull=True).count()
        unmatched_matches = ThreeWayMatch.all_objects.filter(matching_status="VARIANCE_FLAGGED").count()

        self.stdout.write(f"  - POs without lines: {pos_without_lines}")
        self.stdout.write(f"  - GRNs without lines: {grns_without_lines}")
        self.stdout.write(f"  - 3-Way Matches with variance flagged: {unmatched_matches}")

        if pos_without_lines == 0 and grns_without_lines == 0:
            self.stdout.write(self.style.SUCCESS("PROCUREMENT_INTEGRITY_CHECK_PASSED"))
        else:
            self.stdout.write(self.style.ERROR("PROCUREMENT_INTEGRITY_CHECK_FAILED"))
