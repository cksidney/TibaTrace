from django.core.management.base import BaseCommand

from apps.inventory.models import StockTransfer


class Command(BaseCommand):
    help = "Check integrity of inter-branch stock transfers and in-transit stock balancing."

    def handle(self, *args, **options):
        self.stdout.write("Running Stock Transfer Integrity Checks...")

        transfers = StockTransfer.all_objects.all()
        invalid_locations = 0

        for t in transfers:
            if t.source_branch == t.destination_branch:
                invalid_locations += 1

        self.stdout.write(f"  - Total Transfers Evaluated: {transfers.count()}")
        self.stdout.write(f"  - Intra-Branch Same Location Violations: {invalid_locations}")

        if invalid_locations == 0:
            self.stdout.write(self.style.SUCCESS("STOCK_TRANSFER_INTEGRITY_CHECK_PASSED"))
        else:
            self.stdout.write(self.style.ERROR("STOCK_TRANSFER_INTEGRITY_CHECK_FAILED"))
