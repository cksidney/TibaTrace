"""Run context: ownership, collisions and stage progress.

Every object a stage creates or adopts passes through `GenerationContext.own`.
That is the only way a row becomes demo-owned, and demo ownership is the only
thing that makes a row eligible for archival later. A stage that creates a row
without recording it produces data indistinguishable from real tenant data --
which the classifier will then report as REAL_DATA_PRESENT and refuse to seed
over, so the failure surfaces late and confusingly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from django.contrib.contenttypes.models import ContentType

from apps.platform.demo.models import DemoScenarioObject

# ---------------------------------------------------------------------------
# Collision classification
# ---------------------------------------------------------------------------

#: The object already exists, is demo-owned by this run's plan, and matches.
SAFE_REUSE = "SAFE_REUSE"
#: Exists and is demo-owned; a mutable field was reconciled through a service.
SAFE_UPDATE = "SAFE_UPDATE"
#: Exists at the deterministic reference but is not owned by the demo engine.
OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
#: Exists and is demo-owned but an immutable identity field differs.
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
#: Exists but has moved to a lifecycle state the generator cannot re-enter.
LIFECYCLE_CONFLICT = "LIFECYCLE_CONFLICT"
#: Exists in a different tenant.
TENANT_SCOPE_CONFLICT = "TENANT_SCOPE_CONFLICT"
#: Cannot be classified; the run must stop.
BLOCKED = "BLOCKED"

#: Classifications that must stop the run. Reuse and update are the normal
#: outcomes of a rerun; the rest mean the generator would be writing over
#: something it does not own or cannot reconcile.
FATAL_COLLISIONS = frozenset(
    {OWNERSHIP_CONFLICT, IDENTITY_CONFLICT, LIFECYCLE_CONFLICT, TENANT_SCOPE_CONFLICT, BLOCKED}
)


class CollisionError(RuntimeError):
    """Raised when a collision cannot be safely reconciled."""

    def __init__(self, classification: str, reference: str, detail: str):
        self.classification = classification
        self.reference = reference
        self.detail = detail
        super().__init__(f"{classification} at {reference}: {detail}")


@dataclass
class Collision:
    classification: str
    domain: str
    reference: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "classification": self.classification,
            "domain": self.domain,
            "reference": self.reference,
            "detail": self.detail,
        }


@dataclass
class StageResult:
    stage: str
    status: str = "PENDING"
    counts: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    last_key: str = ""
    error_class: str = ""
    error_detail: str = ""

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "counts": dict(sorted(self.counts.items())),
            "seconds": round(self.seconds, 3),
            "last_key": self.last_key,
            "error_class": self.error_class,
            "error_detail": self.error_detail,
        }


class GenerationContext:
    """Shared state for one master-data run."""

    def __init__(self, *, run, tenant, seed: int, as_of, targets, dry_run: bool = False,
                 actor=None, demo_password: str | None = None):
        self.run = run
        self.tenant = tenant
        self.seed = seed
        self.as_of = as_of
        self.targets = targets
        self.dry_run = dry_run
        self.actor = actor
        #: Supplied by the caller from the guarded demo-password mechanism
        #: (apps.core.demo_seed.resolve_demo_password). Held only for the
        #: duration of the run, never written to an artefact, never logged.
        self.demo_password = demo_password

        #: Objects produced per stage, for the summary.
        self.counts: dict[str, int] = {}
        self.collisions: list[Collision] = []
        #: Sub-domains a stage could not generate because the repository has no
        #: authoritative service for them. Recorded rather than worked around:
        #: writing the rows directly would bypass the domain rules the service
        #: would have enforced, and would look identical in the summary.
        self.deferred: list[dict] = []
        self.stage_results: dict[str, StageResult] = {}
        #: Cross-stage handles (sites, departments, users...) keyed by reference.
        self.registry: dict[str, object] = {}
        self._content_types: dict[tuple[str, str], ContentType] = {}

    # -- registry ----------------------------------------------------------

    def put(self, key: str, value):
        self.registry[key] = value
        return value

    def get(self, key: str):
        try:
            return self.registry[key]
        except KeyError:
            raise KeyError(
                f"{key!r} is not in the generation registry. A stage asked for "
                "something an earlier stage should have produced -- check stage "
                "prerequisites and --from-stage."
            ) from None

    def has(self, key: str) -> bool:
        return key in self.registry

    # -- ownership ---------------------------------------------------------

    def _content_type(self, instance) -> ContentType:
        meta = instance._meta
        key = (meta.app_label, meta.model_name)
        if key not in self._content_types:
            self._content_types[key] = ContentType.objects.get_for_model(instance.__class__)
        return self._content_types[key]

    def own(self, instance, *, domain: str, stage: str, story_id: str,
            reference: str, purpose: str = "", relationship_group: str = "",
            reset_eligible: bool = True, branch_reference: str = ""):
        """Record that this run owns an object.

        Idempotent on (run, content_type, object_id), matching the model's
        unique constraint, so a rerun re-registers rather than duplicating.
        """
        if self.dry_run:
            return None
        content_type = self._content_type(instance)
        entry, _ = DemoScenarioObject.all_objects.update_or_create(
            run=self.run,
            content_type=content_type,
            object_id=str(instance.pk),
            defaults={
                "tenant": self.tenant,
                "generator": f"stage-{stage}",
                "seed_key": reference,
                "external_reference": reference,
                "branch_reference": branch_reference,
                "domain": domain,
                "stage": stage,
                "story_id": story_id,
                "relationship_group": relationship_group,
                "business_purpose": purpose[:255],
                "reset_eligible": reset_eligible,
            },
        )
        return entry

    def owned_reference(self, model, reference: str):
        """Find an object this engine previously created at a reference.

        Consults the ownership registry rather than the domain table, so an
        object that merely happens to share a code is not adopted.
        """
        content_type = ContentType.objects.get_for_model(model)
        entry = (
            DemoScenarioObject.all_objects.filter(
                tenant=self.tenant,
                content_type=content_type,
                external_reference=reference,
            )
            .order_by("created_at")
            .first()
        )
        if entry is None:
            return None
        # Scoped by tenant as well as pk. The ownership row was already found
        # by tenant, so this cannot reach another tenant's data -- but a pk-only
        # lookup would still be one edit away from doing so if the ownership
        # query ever loosened, and every model looked up here carries a tenant.
        return model.all_objects.filter(pk=entry.object_id, tenant=self.tenant).first()

    # -- collisions --------------------------------------------------------

    def record_collision(self, classification: str, domain: str, reference: str, detail: str):
        collision = Collision(classification, domain, reference, detail)
        self.collisions.append(collision)
        if classification in FATAL_COLLISIONS:
            raise CollisionError(classification, reference, detail)
        return collision

    def note_reuse(self, domain: str, reference: str, detail: str = "already present"):
        return self.record_collision(SAFE_REUSE, domain, reference, detail)

    # -- counting ----------------------------------------------------------

    def add_count(self, key: str, amount: int = 1):
        self.counts[key] = self.counts.get(key, 0) + amount

    def defer(self, *, domain: str, stage: str, reason: str, required_service: str):
        """Record a sub-domain that cannot be generated authoritatively."""
        self.deferred.append(
            {
                "domain": domain,
                "stage": stage,
                "reason": reason,
                "required_service": required_service,
            }
        )

    # -- stage progress ----------------------------------------------------

    def begin_stage(self, stage: str) -> StageResult:
        result = StageResult(stage=stage, status="RUNNING")
        self.stage_results[stage] = result
        result._started = time.monotonic()  # type: ignore[attr-defined]
        return result

    def finish_stage(self, result: StageResult, *, status: str = "COMPLETED"):
        result.seconds = time.monotonic() - getattr(result, "_started", time.monotonic())
        result.status = status
        self.persist_progress()
        return result

    def persist_progress(self):
        """Write stage progress to the run so --resume can read it."""
        if self.dry_run or self.run is None or self.run.pk is None:
            return
        self.run.stage_progress = {
            stage: result.as_dict() for stage, result in sorted(self.stage_results.items())
        }
        self.run.save(update_fields=["stage_progress", "updated_at"])

    def completed_stages(self) -> set[str]:
        recorded = self.run.stage_progress if self.run is not None else {}
        return {
            stage for stage, data in (recorded or {}).items()
            if isinstance(data, dict) and data.get("status") == "COMPLETED"
        }
