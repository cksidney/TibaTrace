"""Ownership records for demo-generated data.

Every object the demo engine creates is registered against a run, so a later
reset can prove what it may touch. Nothing is reset by inference: if an object
is not in the registry, the engine treats it as real tenant data and leaves it
alone.

Reset is archival, not deletion. Eight model families in this repository declare
themselves immutable -- audit events, clinical overrides, pharmacist
verifications, crosswalks, supplied prescriptions, integration evidence, POS
documents and PO revisions -- so a reset that deleted rows would violate the
repository's own policy. Archiving a run marks its objects superseded and leaves
the records in place.
"""

from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TimestampedModel


class DemoScenarioRun(TimestampedModel):
    """One execution of the demo engine against one tenant."""

    class State(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        DRY_RUN_COMPLETE = "DRY_RUN_COMPLETE", "Dry run complete"
        APPROVED = "APPROVED", "Approved"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        ARCHIVED = "ARCHIVED", "Archived"

    #: Which states may follow which. A run cannot jump from PLANNED to
    #: COMPLETED without evidence of a dry run and an approval in between.
    TRANSITIONS: dict[str, tuple[str, ...]] = {
        State.PLANNED: (State.DRY_RUN_COMPLETE, State.FAILED),
        State.DRY_RUN_COMPLETE: (State.APPROVED, State.PLANNED, State.FAILED),
        State.APPROVED: (State.RUNNING, State.FAILED),
        State.RUNNING: (State.COMPLETED, State.FAILED),
        State.COMPLETED: (State.ARCHIVED,),
        State.FAILED: (State.PLANNED, State.ARCHIVED),
        State.ARCHIVED: (),
    }

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="demo_scenario_runs"
    )
    scenario_name = models.CharField(max_length=120)
    scenario_version = models.CharField(max_length=40)
    profile = models.CharField(max_length=80)
    random_seed = models.BigIntegerField()
    as_of_date = models.DateField()
    scale = models.CharField(max_length=20, default="small")

    state = models.CharField(
        max_length=20, choices=State.choices, default=State.PLANNED, db_index=True
    )

    #: SHA-256 of the dry-run manifest. Production execution requires the digest
    #: the Platform Owner approved; regenerating a different plan invalidates it.
    manifest_digest = models.CharField(max_length=64, blank=True)
    manifest = models.JSONField(default=dict, blank=True)

    #: Provenance of the code that produced the run.
    code_commit = models.CharField(max_length=64, blank=True)
    migration_head = models.CharField(max_length=120, blank=True)
    environment = models.CharField(max_length=40, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)

    #: Set when a run supersedes an earlier one for the same tenant and profile.
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="supersedes"
    )

    # Tenant-owned: the default manager is tenant-scoped, and all_objects is
    # the deliberate escape hatch for management commands that have no
    # tenant context set.
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # One live run per (tenant, profile, seed, as-of). Rerunning the same
            # plan must find this row rather than create a second one -- that is
            # the idempotency anchor for the whole engine.
            models.UniqueConstraint(
                fields=["tenant", "profile", "scenario_version", "random_seed", "as_of_date"],
                name="uniq_demo_run_plan",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "state"], name="ix_demorun_tenant_state")]

    def __str__(self) -> str:
        return f"{self.tenant.slug}/{self.profile}@{self.scenario_version} [{self.state}]"

    def transition_to(self, new_state: str, *, reason: str = "") -> None:
        allowed = self.TRANSITIONS.get(self.state, ())
        if new_state not in allowed:
            raise ValidationError(
                f"Demo scenario run cannot move {self.state} -> {new_state}. "
                f"Allowed: {', '.join(allowed) or 'none (terminal)'}"
            )
        self.state = new_state
        if reason:
            self.failure_reason = reason
        self.save(update_fields=["state", "failure_reason", "updated_at"])


class DemoScenarioObject(TimestampedModel):
    """Registry entry proving one object was created by the demo engine.

    Reset consults this and nothing else. An object absent from here is treated
    as real tenant data.
    """

    run = models.ForeignKey(
        DemoScenarioRun, on_delete=models.CASCADE, related_name="objects_created"
    )
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="demo_scenario_objects"
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    target = GenericForeignKey("content_type", "object_id")

    #: Which generator produced it, for tracing a bad record back to its source.
    generator = models.CharField(max_length=120)
    #: Stable key derived from the seed, so a rerun recognises its own output.
    seed_key = models.CharField(max_length=200, db_index=True)
    branch_reference = models.CharField(max_length=120, blank=True)

    #: False for immutable domains -- audit, ledger, clinical decisions and the
    #: rest. Archival supersedes them; nothing deletes them.
    reset_eligible = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Tenant-owned: the default manager is tenant-scoped, and all_objects is
    # the deliberate escape hatch for management commands that have no
    # tenant context set.
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["run", "content_type", "object_id"], name="uniq_demo_object_per_run"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "content_type"], name="ix_demoobj_tenant_ct"),
            models.Index(fields=["run", "reset_eligible"], name="ix_demoobj_run_reset"),
        ]

    def __str__(self) -> str:
        return f"{self.content_type.app_label}.{self.content_type.model}:{self.object_id}"


class DemoSeedApproval(TimestampedModel):
    """Platform Owner approval for running the engine against production.

    Separation of duty is enforced in the database, not only in the workflow:
    a requester cannot be the approver.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        CONSUMED = "CONSUMED", "Consumed"

    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, related_name="demo_seed_approvals"
    )
    run = models.ForeignKey(
        DemoScenarioRun, on_delete=models.CASCADE, related_name="approvals", null=True, blank=True
    )

    requested_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="demo_seed_requests"
    )
    approved_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="demo_seed_approvals_given",
        null=True,
        blank=True,
    )

    request_reason = models.TextField()
    profile = models.CharField(max_length=80)
    scenario_version = models.CharField(max_length=40)
    random_seed = models.BigIntegerField()
    as_of_date = models.DateField()

    #: The approval binds to one exact plan. A different manifest is a different
    #: plan and must be approved again.
    manifest_digest = models.CharField(max_length=64)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    approved_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    audit_correlation_id = models.CharField(max_length=64, blank=True)

    # Tenant-owned: the default manager is tenant-scoped, and all_objects is
    # the deliberate escape hatch for management commands that have no
    # tenant context set.
    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "status"], name="ix_demoappr_tenant_status"),
            models.Index(fields=["manifest_digest"], name="ix_demoappr_digest"),
        ]

    def clean(self):
        super().clean()
        if self.approved_by_id and self.approved_by_id == self.requested_by_id:
            raise ValidationError(
                "The requester of a demo seed cannot approve it. Production demo "
                "seeding requires two people."
            )

    def save(self, *args, **kwargs):
        self.full_clean(exclude=None, validate_unique=False)
        return super().save(*args, **kwargs)

    def is_usable(self, *, now, manifest_digest: str) -> tuple[bool, str]:
        """Whether this approval authorises a run right now."""
        if self.status != self.Status.APPROVED:
            return False, f"approval status is {self.status}, not APPROVED"
        if self.expires_at <= now:
            return False, "approval has expired"
        if self.manifest_digest != manifest_digest:
            return False, "manifest digest does not match the approved plan"
        return True, ""
