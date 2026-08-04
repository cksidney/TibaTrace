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

        # Stage 2A / Stage 2B
        parser.add_argument(
            "--stage", choices=["master-data", "procurement-receiving", "procurement-quality", "inventory-ownership", "stock-mobility"],
            help="Generation stage to execute. Omit to plan only.",
        )
        parser.add_argument("--demo-version", help="Dated content version, e.g. 2026.08.03.")
        parser.add_argument("--scenario-version", help="Plan version, e.g. 1.0.")
        parser.add_argument(
            "--manifest-digest",
            help="The approved manifest digest. Refuses to run if the computed plan differs.",
        )
        parser.add_argument("--resume", action="store_true",
                            help="Continue an interrupted run from its last completed stage.")
        parser.add_argument("--from-stage", help="First stage to run (A-L).")
        parser.add_argument("--stop-after-stage", help="Last stage to run (A-L).")
        parser.add_argument("--output-directory", help="Where evidence artefacts are written.")
        parser.add_argument("--progress-format", choices=["text", "json"], default="text")

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

        if options.get("stage") in {"master-data", "procurement-receiving", "procurement-quality"}:
            return self._run_master_data(
                tenant=tenant, profile=profile, seed=seed, as_of=as_of,
                manifest=manifest, digest=digest, options=options,
            )

        raise CommandError(
            "Transactional generation (inventory ledger, prescriptions, sales, claims) "
            "is Stage 2B and is deliberately absent, so an empty tenant is never "
            "mistaken for a successful seed.\n"
            "Use --stage=master-data for Stage 2A, --stage=procurement-receiving for Stage 2B.1, "
            "--stage=procurement-quality for Stage 2B.2A, or --dry-run / --validate-only."
        )

    # ------------------------------------------------------------------
    # Stage 2A / 2B
    # ------------------------------------------------------------------

    def _run_master_data(self, *, tenant, profile, seed, as_of, manifest, digest, options):
        from pathlib import Path

        from apps.core.demo_seed import resolve_demo_password
        from apps.platform.demo.generation.context import GenerationContext
        from apps.platform.demo.generation.orchestrator import MasterDataOrchestrator
        from apps.platform.demo.generation.validation import MasterDataValidator
        from apps.platform.demo.profiles import DEMO_VERSION, get_master_data_targets

        supplied_digest = options.get("manifest_digest")
        if supplied_digest and supplied_digest != digest:
            raise CommandError(
                "The approved manifest digest does not match the plan this run would "
                f"produce.\n  approved: {supplied_digest}\n  computed: {digest}\n"
                "An approval authorises one exact plan. Re-run the dry run and obtain "
                "approval for the new digest."
            )

        try:
            targets = get_master_data_targets(options["scale"])
        except KeyError as exc:
            raise CommandError(str(exc)) from None

        # Guarded credential: never generated inline, never printed, never
        # written to an artefact.
        password, _generated = resolve_demo_password(
            allow_generated_fallback=options.get("allow_demo_seed", False)
        )

        run = self._ensure_run(tenant, profile, seed, as_of, options["scale"], manifest, digest)
        ctx = GenerationContext(
            run=run, tenant=tenant, seed=seed, as_of=as_of, targets=targets,
            demo_password=password,
        )

        json_progress = options.get("progress_format") == "json"

        def report(message: str):
            if json_progress:
                self.stdout.write(json.dumps({"event": "stage", "message": message}))
            else:
                self.stdout.write(f"  {message}")

        stage_name = options.get("stage")
        is_stage_2b1 = stage_name == "procurement-receiving"
        is_stage_2b2a = stage_name == "procurement-quality"
        is_stage_2b2b = stage_name == "inventory-ownership"
        is_stage_2c = stage_name == "stock-mobility"

        if is_stage_2b1 or is_stage_2b2a or is_stage_2b2b or is_stage_2c:
            from apps.platform.demo.generation.orchestrator import (
                STAGE_2B_ARTEFACTS,
                STAGE_2B2B_ARTEFACTS,
                STAGE_2C_ARTEFACTS,
            )
            from apps.platform.demo.generation.stage2b import STAGE_2B_1
            from apps.platform.demo.generation.stage2b2 import STAGE_2B_2A, STAGE_2B_2B
            from apps.platform.demo.generation.stage2c import STAGE_2C

            if is_stage_2c:
                stage_set = STAGE_2B_1 + STAGE_2B_2A + STAGE_2B_2B + STAGE_2C
                artefact_names = STAGE_2C_ARTEFACTS
            elif is_stage_2b2b:
                stage_set = STAGE_2B_1 + STAGE_2B_2A + STAGE_2B_2B
                artefact_names = STAGE_2B2B_ARTEFACTS
            elif is_stage_2b2a:
                stage_set = STAGE_2B_1 + STAGE_2B_2A
                artefact_names = STAGE_2B_ARTEFACTS
            else:
                stage_set = STAGE_2B_1
                artefact_names = STAGE_2B_ARTEFACTS

            from apps.platform.demo.generation.stages import STAGES as MASTER_STAGES

            for stage in MASTER_STAGES:
                stage.rehydrate(ctx)
        else:
            stage_set = None
            artefact_names = None

        orchestrator = MasterDataOrchestrator(
            ctx, progress=report, stages=stage_set, artefact_names=artefact_names
        )
        try:
            orchestrator.run(
                from_stage=options.get("from_stage"),
                stop_after=options.get("stop_after_stage"),
                resume=options.get("resume", False),
            )
        except Exception as exc:
            run.refresh_from_db()
            run.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
            run.save(update_fields=["failure_reason", "updated_at"])
            raise CommandError(f"Master-data generation failed: {exc}") from exc

        if is_stage_2c:
            from apps.platform.demo.generation.validation import StockMobilityValidator

            validation = StockMobilityValidator(run=run, tenant=tenant).run_all()
        elif is_stage_2b2b:
            from apps.platform.demo.generation.validation import QualityInventoryValidator

            validation = QualityInventoryValidator(run=run, tenant=tenant).run_all()
        elif is_stage_2b2a:
            from apps.platform.demo.generation.validation import QualityValidator

            validation = QualityValidator(run=run, tenant=tenant).run_all()
        elif is_stage_2b1:
            from apps.platform.demo.generation.validation import (
                ProcurementReceivingValidator,
            )

            validation = ProcurementReceivingValidator(run=run, tenant=tenant).run_all()
        else:
            validation = MasterDataValidator(run=run, tenant=tenant).run_all()

        orchestrator.finalise()

        directory = Path(
            options.get("output_directory")
            or f"demo-evidence/{tenant.slug}/{DEMO_VERSION}/{digest[:12]}"
        )
        written = orchestrator.write_artefacts(directory, validation=validation)

        summary = orchestrator.summary()
        self._print_master_data(summary, validation, written, orchestrator)

        if validation["status"] != "PASS":
            raise CommandError(
                f"Master-data validation FAILED with {validation['failure_count']} finding(s). "
                "The run is not marked complete."
            )
        self.stdout.write(self.style.SUCCESS("MASTER_DATA_COMPLETE"))

    def _ensure_run(self, tenant, profile, seed, as_of, scale, manifest, digest):
        from apps.platform.demo.profiles import DEMO_VERSION

        run, _ = DemoScenarioRun.all_objects.get_or_create(
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
        run.demo_version = DEMO_VERSION
        run.save(update_fields=["manifest", "manifest_digest", "demo_version", "updated_at"])
        return run

    def _print_master_data(self, summary, validation, written, orchestrator):
        self.stdout.write("")
        self.stdout.write("Master data generated")
        for key, value in sorted(summary["counts"].items()):
            if "." not in key:
                self.stdout.write(f"  {key:38} {value}")
        if summary["deferred"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Deferred (no authoritative service):"))
            for entry in summary["deferred"]:
                self.stdout.write(f"  - {entry['domain']}: needs {entry['required_service']}")
        self.stdout.write("")
        status_style = self.style.SUCCESS if validation["status"] == "PASS" else self.style.ERROR
        self.stdout.write(status_style(f"Validation: {validation['status']}"))
        for finding in validation["findings"]:
            if finding["status"] != "PASS":
                self.stdout.write(f"  {finding['status']}: {finding['check']} — {finding['detail']}")
        self.stdout.write("")
        self.stdout.write(f"Artefacts: {len(written)} file(s)")
        for name in sorted(written):
            self.stdout.write(f"  {written[name]}")
        self.stdout.write(f"Total: {orchestrator.timings()['total_seconds']}s")

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
