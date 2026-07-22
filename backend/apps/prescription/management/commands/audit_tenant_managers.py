from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.prescription.management.manager_safety import audit_tenant_managers


class Command(BaseCommand):
    help = "Fail when a tenant-owned model has an unreviewed unrestricted default manager."

    def handle(self, *args, **options):
        result = audit_tenant_managers()
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
        if result["findings"]:
            raise CommandError("Unrestricted tenant model managers detected.")
