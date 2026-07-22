from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.prescription.management.lookup_safety import find_unscoped_uuid_lookups


class Command(BaseCommand):
    help = "Fail when healthcare or FHIR code contains a direct unscoped UUID ORM lookup."

    def handle(self, *args, **options):
        app_root = Path(settings.BASE_DIR) / "apps"
        findings = [finding.as_dict() for finding in find_unscoped_uuid_lookups(app_root)]
        payload = {
            "source_roots": [str(app_root)],
            "finding_count": len(findings),
            "findings": findings,
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
        if findings:
            raise CommandError("Unscoped healthcare/FHIR UUID lookups detected.")
