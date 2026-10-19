from django.core.management.base import BaseCommand, CommandError

from apps.inventory.reconciliation import reconcile
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = 'Compare physical and per-batch reservation ledger totals with derived custody balances.'

    def add_arguments(self, parser):
        parser.add_argument('--repair-projections', action='store_true')
        parser.add_argument('--tenant-id', type=str)

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options['tenant_id']:
            tenants = tenants.filter(pk=options['tenant_id'])
            if not tenants.exists():
                raise CommandError('Tenant not found.')
        total = 0
        for tenant in tenants:
            issues = reconcile(tenant, repair=options['repair_projections'])
            total += len(issues)
            for issue in issues:
                self.stdout.write(f'{tenant.pk}: projection mismatch {issue}')
        self.stdout.write(f'Integrity check complete. Total issues found: {total}')
        if options['repair_projections']:
            self.stdout.write(f'Repaired {total} projections. Source ledger unchanged.')
        elif total:
            raise CommandError(f'{total} inventory projection mismatches.')
