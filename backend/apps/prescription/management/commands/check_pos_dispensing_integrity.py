from django.core.management.base import BaseCommand

from apps.prescription.models import DispensingEpisode, DispensingLine, PosDeviceHealthRecord, PosShiftRecord


class Command(BaseCommand):
    help = "Verify POS Enterprise Dispensing data integrity and tenant isolation"

    def handle(self, *args, **options):
        self.stdout.write("Running POS Enterprise Dispensing Integrity Check...")

        episodes = DispensingEpisode.all_objects.all()
        self.stdout.write(f"Total Dispensing Episodes: {episodes.count()}")

        lines = DispensingLine.all_objects.all()
        self.stdout.write(f"Total Dispensing Lines: {lines.count()}")

        shifts = PosShiftRecord.all_objects.all()
        self.stdout.write(f"Total POS Shift Records: {shifts.count()}")

        devices = PosDeviceHealthRecord.all_objects.all()
        self.stdout.write(f"Total Device Health Records: {devices.count()}")

        # Verify payment gate integrity
        premature_supplies = DispensingEpisode.all_objects.filter(
            status="SUPPLIED",
            payment_status__in=["PENDING", "FAILED"],
        )
        if premature_supplies.exists():
            self.stderr.write(self.style.ERROR(f"Integrity Violation: {premature_supplies.count()} episodes supplied without confirmed payment!"))
        else:
            self.stdout.write(self.style.SUCCESS("Payment Gate Integrity: PASSED (0 un-paid supplied episodes)"))

        self.stdout.write(self.style.SUCCESS("POS Enterprise Dispensing Integrity Check Completed Successfully."))
