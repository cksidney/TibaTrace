from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.prescription.management.tenant_ownership import audit_ownership


class Command(BaseCommand):
    help = "Audit clinical tenant ownership without emitting patient-sensitive fields."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        result = audit_ownership(limit=max(1, min(options["limit"], 100)))
        if options["as_json"]:
            self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
        else:
            for model_name, row in result["models"].items():
                self.stdout.write(f"{model_name}: {row}")
            for relation, count in result["mismatches"].items():
                self.stdout.write(f"{relation}: mismatch_count={count}")
            self.stdout.write(f"safe_to_enforce={result['safe_to_enforce']}")
        if not result["safe_to_enforce"]:
            raise CommandError("Clinical tenant ownership audit failed.")
