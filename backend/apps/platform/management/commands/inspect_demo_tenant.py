"""Classify what already exists in a tenant, before anything is seeded.

Read-only. Answers the question the safety gates depend on: is this tenant
empty, demo-owned, or carrying real work nobody can account for?
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.platform.demo.classification import classify_tenant
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Classify existing data in a tenant prior to demo seeding (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-slug", required=True)
        parser.add_argument("--tenant-id", help="Exact tenant UUID; verified against the slug.")
        parser.add_argument("--json", action="store_true", help="Emit the report as JSON only.")
        parser.add_argument("--output", help="Write the JSON report to this path.")

    def handle(self, *args, **options):
        slug = options["tenant_slug"]
        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            raise CommandError(f"No tenant with slug {slug!r}.")

        supplied_id = options.get("tenant_id")
        if supplied_id and str(tenant.id) != str(supplied_id):
            raise CommandError(
                "--tenant-id does not match the tenant found by slug. Refusing to "
                "report on a tenant you did not identify."
            )

        report = classify_tenant(tenant)
        payload = report.as_dict()

        if options.get("output"):
            with open(options["output"], "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.write("\n")

        if options.get("json"):
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
            return

        self.stdout.write(f"Tenant   {tenant.slug}  ({tenant.name})")
        self.stdout.write(f"  id       {tenant.id}")
        self.stdout.write(f"  is_demo  {tenant.is_demo}")
        self.stdout.write(f"  demo runs {report.demo_runs}")
        self.stdout.write("")
        self.stdout.write(f"  {'domain':30} {'total':>7} {'demo':>7} {'unaccounted':>12}  immutable")
        for label, dc in sorted(report.domains.items()):
            if not dc.available:
                self.stdout.write(f"  {label:30} {'n/a':>7}")
                continue
            self.stdout.write(
                f"  {label:30} {dc.total:>7} {dc.demo_owned:>7} {dc.unaccounted:>12}"
                f"  {'yes' if dc.immutable else ''}"
            )
        self.stdout.write("")
        for note in report.notes:
            self.stdout.write(f"  note: {note}")
        self.stdout.write("")
        self.stdout.write(report.verdict)
