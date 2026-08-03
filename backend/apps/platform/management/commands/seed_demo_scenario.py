"""Demo scenario engine entrypoint.

Stage 1 implements planning only: safety gates, existing-data classification,
the deterministic manifest and the scenario run record. It deliberately refuses
to generate transactional data -- attempting a real run reports that generation
is not yet implemented rather than silently doing nothing, so nobody mistakes an
empty tenant for a successful seed.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.demo_seed import add_demo_seed_arguments
from apps.platform.demo import safety
from apps.platform.demo.classification import classify_tenant
from apps.platform.demo.manifest import build_manifest, finalise
from apps.platform.demo.models import DemoScenarioRun, DemoSeedApproval
from apps.platform.demo.profiles import SCENARIO_NAME, SCENARIO_VERSION, get_profile
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Plan (Stage 1) or run the Nairobi Chemists demo scenario."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-slug", required=True)
        parser.add_argument("--profile", default="nairobi-chemists-pilot")
        parser.add_argument("--random-seed", type=int, required=True)
        parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
        parser.add_argument("--scale", default="small", choices=["small", "medium", "large"])
        parser.add_argument("--years", type=int, help="Reserved for later stages.")
        parser.add_argument("--skip-domain", action="append", default=[])
        parser.add_argument("--include-edge-cases", action="store_true")
        parser.add_argument("--output-manifest")

        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--validate-only", action="store_true")
        parser.add_argument("--reset-demo-data", action="store_true")

        # Identity confirmations.
        parser.add_argument("--confirm-tenant-slug")
        parser.add_argument("--confirm-tenant-id")
        parser.add_argument("--confirm-tenant-name")

        # Production exception. Separate from --allow-demo-seed by design.
        parser.add_argument("--allow-production-demo-seed", action="store_true")
        parser.add_argument("--backup-reference", help="Evidence a backup exists.")

        add_demo_seed_arguments(parser)

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=options["tenant_slug"]).first()
        if tenant is None:
            raise CommandError(
                f"No tenant with slug {options['tenant_slug']!r}. The engine never "
                "creates a tenant -- designate an existing one instead."
            )

        try:
            profile = get_profile(options["profile"])
        except KeyError as exc:
            raise CommandError(str(exc)) from None

        as_of = self._parse_date(options["as_of_date"])
        seed = options["random_seed"]

        report = classify_tenant(tenant)
        manifest = finalise(
            build_manifest(
                tenant=tenant,
                profile=profile,
                random_seed=seed,
                as_of_date=as_of,
                environment=safety.resolved_environment() or "unset",
                existing_counts=report.counts(),
                data_classification=report.verdict,
                scale=options["scale"],
            )
        )
        digest = manifest["manifest_sha256"]

        if options.get("output_manifest"):
            with open(options["output_manifest"], "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2, sort_keys=True)
                fh.write("\n")

        approval = self._approval_for(tenant, digest)
        gates = safety.evaluate_all(
            tenant=tenant,
            allow_demo_seed=options.get("allow_demo_seed", False),
            allow_production_demo_seed=options.get("allow_production_demo_seed", False),
            confirm_slug=options.get("confirm_tenant_slug"),
            confirm_id=options.get("confirm_tenant_id"),
            confirm_name=options.get("confirm_tenant_name"),
            approval=approval,
            manifest_digest=digest,
            backup_present=bool(options.get("backup_reference")),
            capacity_ok=True,
            data_classification=report.verdict,
        )

        self._print_plan(tenant, profile, report, manifest, gates)

        if options["validate_only"]:
            gates.raise_if_blocked()
            self.stdout.write(self.style.SUCCESS("VALIDATE_ONLY_PASSED"))
            return

        if options["dry_run"]:
            gates.raise_if_blocked()
            self._record_dry_run(tenant, profile, seed, as_of, options["scale"], manifest, digest)
            self.stdout.write(self.style.SUCCESS("DRY_RUN_COMPLETE"))
            self.stdout.write(f"manifest_sha256={digest}")
            return

        if options["reset_demo_data"]:
            raise CommandError(
                "Reset is not implemented in Stage 1. Scenario archival exists; "
                "destructive reset does not, and will not delete immutable audit, "
                "ledger or clinical records when it does."
            )

        gates.raise_if_blocked()
        raise CommandError(
            "Stage 1 implements planning only: gates, classification, manifest and "
            "the run record. Transactional generation (patients, inventory, "
            "prescriptions, sales, claims) is Stage 2 and is deliberately absent, "
            "so an empty tenant is never mistaken for a successful seed.\n"
            "Use --dry-run or --validate-only."
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(raw: str) -> date:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError(f"--as-of-date must be YYYY-MM-DD, got {raw!r}") from None

    @staticmethod
    def _approval_for(tenant, digest: str):
        return (
            DemoSeedApproval.all_objects.filter(
                tenant=tenant,
                manifest_digest=digest,
                status=DemoSeedApproval.Status.APPROVED,
            )
            .order_by("-approved_at")
            .first()
        )

    @transaction.atomic
    def _record_dry_run(self, tenant, profile, seed, as_of, scale, manifest, digest) -> None:
        run, created = DemoScenarioRun.all_objects.get_or_create(
            tenant=tenant,
            profile=profile.key,
            scenario_version=SCENARIO_VERSION,
            random_seed=seed,
            as_of_date=as_of,
            defaults={
                "scenario_name": SCENARIO_NAME,
                "scale": scale,
                "state": DemoScenarioRun.State.PLANNED,
            },
        )
        run.manifest = manifest
        run.manifest_digest = digest
        run.code_commit = manifest.get("code_commit", "")
        run.migration_head = manifest.get("migration_head", "")
        run.environment = manifest.get("environment", "")
        run.save(
            update_fields=[
                "manifest", "manifest_digest", "code_commit",
                "migration_head", "environment", "updated_at",
            ]
        )
        if run.state == DemoScenarioRun.State.PLANNED:
            run.transition_to(DemoScenarioRun.State.DRY_RUN_COMPLETE)
        self.stdout.write(f"  run {'created' if created else 'reused'}: {run.id}")

    def _print_plan(self, tenant, profile, report, manifest, gates) -> None:
        self.stdout.write("")
        self.stdout.write(f"Tenant       {tenant.slug}  ({tenant.name})")
        self.stdout.write(f"  id           {tenant.id}")
        self.stdout.write(f"  is_demo      {tenant.is_demo}")
        self.stdout.write(f"  environment  {manifest['environment']}")
        self.stdout.write(f"Profile      {profile.key}  v{SCENARIO_VERSION}")
        self.stdout.write(f"  seed         {manifest['random_seed']}")
        self.stdout.write(f"  as-of        {manifest['as_of_date']}")
        self.stdout.write(f"  history      {profile.months_of_history} months")
        self.stdout.write("")
        self.stdout.write(f"Existing data: {report.verdict}")
        self.stdout.write("")
        self.stdout.write("Planned objects:")
        for key, value in manifest["planned_object_counts"].items():
            self.stdout.write(f"  {key:32} {value:>7}")
        self.stdout.write(f"  {'TOTAL':32} {manifest['planned_total']:>7}")
        self.stdout.write("")
        self.stdout.write(
            f"Estimated growth ~{manifest['expected_storage_growth_mb']} MB, "
            f"runtime ~{manifest['expected_runtime_minutes']} min (unmeasured)"
        )
        self.stdout.write("")
        self.stdout.write(f"Excluded domains ({len(manifest['excluded_domains'])}):")
        for key, why in manifest["excluded_domains"].items():
            self.stdout.write(f"  {key:24} {why}")
        self.stdout.write("")
        self.stdout.write(f"Safety gates: {len(gates.passed)} passed, {len(gates.failed)} failed")
        for item in gates.passed:
            self.stdout.write(f"  ok    {item}")
        for item in gates.failed:
            self.stdout.write(self.style.ERROR(f"  FAIL  {item}"))
        self.stdout.write("")
