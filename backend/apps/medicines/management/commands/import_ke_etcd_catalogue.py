from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.medicines.government_catalogue import (
    GovernmentCatalogueError,
    import_government_catalogue,
    load_government_catalogue,
)


class Command(BaseCommand):
    help = "Validate and import the Kenya eTCD government product catalogue as inactive global medicines."

    def add_arguments(self, parser):
        parser.add_argument("catalogue", type=Path)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist accepted rows. Without this option the command only validates and reports.",
        )
        parser.add_argument(
            "--report",
            type=Path,
            help="Write the validation and quarantine report to this JSON file.",
        )

    def handle(self, *args, **options):
        try:
            plan = load_government_catalogue(options["catalogue"])
        except GovernmentCatalogueError as exc:
            raise CommandError(str(exc)) from exc

        report = plan.report()
        if options["apply"]:
            try:
                result = import_government_catalogue(plan)
            except GovernmentCatalogueError as exc:
                raise CommandError(str(exc)) from exc
            report["import"] = result.report()

        report_path = options.get("report")
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS("Kenya eTCD catalogue imported as inactive reference medicines."))
        else:
            self.stdout.write(self.style.WARNING("Dry run only; no catalogue records were changed."))
