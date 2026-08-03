"""Stage orchestration, resume and artefacts.

The orchestrator owns three things a plain loop over stages would get wrong:
prerequisite checking, resume, and failure recording. A stage that fails must
leave enough behind to continue from -- which stage, what it had reached, and
what kind of error -- because the alternative is re-running eleven stages to
retry the twelfth.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from django.utils import timezone

from apps.platform.demo.profiles import (
    DEMO_VERSION,
    MASTER_DATA_SCENARIO_VERSION,
    SCENARIO_LABEL,
    STAGE_2A_FORBIDDEN_DOMAINS,
)

from .context import CollisionError, GenerationContext
from .stages import STAGE_ORDER, STAGES, STAGES_BY_ID

ARTEFACTS = (
    "MASTER_DATA_MANIFEST.json",
    "MASTER_DATA_SUMMARY.json",
    "MASTER_DATA_VALIDATION.json",
    "MASTER_DATA_COLLISIONS.json",
    "MASTER_DATA_TIMINGS.json",
    "MASTER_DATA_KPIS.json",
)


def canonical_digest(payload) -> str:
    """SHA-256 over canonical JSON.

    Sorted keys and no whitespace, so the digest depends on content and not on
    dict insertion order or formatting. This is what an approval binds to.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class MasterDataOrchestrator:
    """Runs the master-data stages for one scenario run."""

    def __init__(self, ctx: GenerationContext, *, progress=None):
        self.ctx = ctx
        self.progress = progress or (lambda message: None)
        self.started_at = None
        self.finished_at = None

    # -- planning ----------------------------------------------------------

    def plan(self) -> dict:
        """Planned counts, without touching the database."""
        planned: dict[str, int] = {}
        for stage in STAGES:
            for key, value in stage.plan(self.ctx).items():
                planned[key] = planned.get(key, 0) + value
        return planned

    def manifest(self) -> dict:
        """The deterministic plan. Identical inputs produce an identical digest."""
        ctx = self.ctx
        body = {
            "scenario": {
                "name": SCENARIO_LABEL,
                "scenario_version": MASTER_DATA_SCENARIO_VERSION,
                "demo_version": DEMO_VERSION,
                "profile": ctx.run.profile if ctx.run else "",
                "stage": "master-data",
            },
            "tenant": {
                "id": str(ctx.tenant.id),
                "slug": ctx.tenant.slug,
                "name": ctx.tenant.name,
                "is_demo": bool(ctx.tenant.is_demo),
            },
            "determinism": {
                "random_seed": ctx.seed,
                "as_of_date": ctx.as_of.isoformat(),
            },
            "planned_counts": dict(sorted(self.plan().items())),
            "stages": [
                {"id": s.id, "label": s.label, "requires": list(s.requires)} for s in STAGES
            ],
            "forbidden_domains": dict(sorted(STAGE_2A_FORBIDDEN_DOMAINS.items())),
        }
        body["manifest_digest"] = canonical_digest(body)
        return body

    # -- execution ---------------------------------------------------------

    def run(self, *, from_stage: str | None = None, stop_after: str | None = None,
            resume: bool = False) -> dict:
        ctx = self.ctx
        self.started_at = time.monotonic()
        completed = ctx.completed_stages() if resume else set()

        selected = self._select(from_stage, stop_after)
        for stage in selected:
            if resume and stage.id in completed:
                # Rehydrate rather than re-run: later stages need this stage's
                # handles, but re-running it would repeat lifecycle transitions
                # that are not idempotent.
                stage.rehydrate(ctx)
                self.progress(f"stage {stage.id} already complete; rehydrated")
                continue

            missing = [
                dep for dep in stage.requires
                if dep not in completed and dep not in {s.id for s in selected[: selected.index(stage)]}
            ]
            if missing:
                raise RuntimeError(
                    f"Stage {stage.id} requires {', '.join(missing)}, which has not run. "
                    "Use --from-stage with care, or --resume to continue an existing run."
                )

            result = ctx.begin_stage(stage.id)
            self.progress(f"stage {stage.id}: {stage.label}")
            try:
                stage.run(ctx)
            except CollisionError as exc:
                result.error_class = exc.classification
                result.error_detail = str(exc)
                ctx.finish_stage(result, status="FAILED")
                raise
            except Exception as exc:
                result.error_class = type(exc).__name__
                result.error_detail = str(exc)[:2000]
                ctx.finish_stage(result, status="FAILED")
                raise
            result.counts = {
                k: v for k, v in ctx.counts.items()
            }
            ctx.finish_stage(result, status="COMPLETED")
            completed.add(stage.id)

        self.finished_at = time.monotonic()
        return self.summary()

    def _select(self, from_stage, stop_after) -> list:
        order = list(STAGE_ORDER)
        start = order.index(from_stage) if from_stage else 0
        end = order.index(stop_after) + 1 if stop_after else len(order)
        if from_stage and from_stage not in STAGES_BY_ID:
            raise KeyError(f"Unknown stage {from_stage!r}. Known: {', '.join(order)}")
        if stop_after and stop_after not in STAGES_BY_ID:
            raise KeyError(f"Unknown stage {stop_after!r}. Known: {', '.join(order)}")
        return [STAGES_BY_ID[s] for s in order[start:end]]

    # -- artefacts ---------------------------------------------------------

    def summary(self) -> dict:
        ctx = self.ctx
        counts = dict(sorted(ctx.counts.items()))
        return {
            "scenario": SCENARIO_LABEL,
            "scenario_version": MASTER_DATA_SCENARIO_VERSION,
            "demo_version": DEMO_VERSION,
            "tenant": {"slug": ctx.tenant.slug, "id": str(ctx.tenant.id)},
            "random_seed": ctx.seed,
            "as_of_date": ctx.as_of.isoformat(),
            "counts": counts,
            "totals": {
                "objects_recorded": sum(
                    v for k, v in counts.items() if "." not in k and not k.endswith("_available")
                ),
                "stages_run": len(ctx.stage_results),
            },
            "deferred": ctx.deferred,
            "truth_labels": {
                "practitioner_verification": "MANUAL_INTERNAL_VERIFICATION",
                "external_connectivity": "NOT_EXTERNALLY_CONNECTED",
                "insurer_environment": "SANDBOX",
                "insurer_adapter": "FAKE",
            },
        }

    def timings(self) -> dict:
        return {
            "stages": [r.as_dict() for _, r in sorted(self.ctx.stage_results.items())],
            "total_seconds": round(
                (self.finished_at or time.monotonic()) - (self.started_at or time.monotonic()), 3
            ),
        }

    def collisions(self) -> dict:
        return {
            "collisions": [c.as_dict() for c in self.ctx.collisions],
            "counts_by_classification": self._classification_counts(),
        }

    def _classification_counts(self) -> dict:
        counts: dict[str, int] = {}
        for collision in self.ctx.collisions:
            counts[collision.classification] = counts.get(collision.classification, 0) + 1
        return dict(sorted(counts.items()))

    def kpis(self) -> dict:
        """Master-data KPIs only.

        No revenue, no dispensing time, no stock turn: Stage 2A creates no
        transactions, so any such figure would be fabricated.
        """
        counts = self.ctx.counts
        sites = counts.get("sites", 0)
        users = counts.get("users", 0)
        return {
            "note": "Master-data coverage only. Stage 2A creates no transactions, so no "
                    "revenue, dispensing or stock-turn KPI can be derived.",
            "sites": sites,
            "departments": counts.get("departments", 0),
            "departments_per_site": round(counts.get("departments", 0) / sites, 2) if sites else 0,
            "users": users,
            "users_with_primary_department": counts.get("department_memberships", 0),
            "roles": counts.get("roles", 0),
            "practitioners": counts.get("practitioners", 0),
            "practitioners_with_controlled_authority": counts.get(
                "practitioners_controlled_authority", 0),
            "patients": counts.get("patients", 0),
            "manufacturers": counts.get("manufacturers", 0),
            "suppliers": counts.get("suppliers", 0),
            "insurers": counts.get("insurers", 0),
            "insurer_plans": counts.get("insurer_plans", 0),
            "inventory_locations": counts.get("inventory_locations", 0),
            "deferred_domains": len(self.ctx.deferred),
        }

    def write_artefacts(self, directory: Path, *, validation: dict) -> dict[str, str]:
        directory.mkdir(parents=True, exist_ok=True)
        payloads = {
            "MASTER_DATA_MANIFEST.json": self.manifest(),
            "MASTER_DATA_SUMMARY.json": self.summary(),
            "MASTER_DATA_VALIDATION.json": validation,
            "MASTER_DATA_COLLISIONS.json": self.collisions(),
            "MASTER_DATA_TIMINGS.json": self.timings(),
            "MASTER_DATA_KPIS.json": self.kpis(),
        }
        written = {}
        for name, payload in payloads.items():
            path = directory / name
            # sort_keys so the file bytes are deterministic for equal content.
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            written[name] = str(path)
        return written

    def finalise(self, *, generated_at=None):
        run = self.ctx.run
        if run is None:
            return
        run.finished_at = generated_at or timezone.now()
        run.save(update_fields=["finished_at", "updated_at"])
