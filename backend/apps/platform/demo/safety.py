"""Safety gates for the demo scenario engine.

The engine writes fabricated trading history. Nairobi Chemists is a designated
demo tenant that nevertheless lives in the production database, so the usual
"never in production" rule is replaced by a narrow, evidenced exception: every
condition must hold, and every one is checked independently.

Two rules that do not bend:

* ``--allow-demo-seed`` never permits production seeding. It establishes
  non-production intent and nothing more. Production needs its own explicit
  flag *and* a Platform Owner approval bound to an exact manifest digest.
* Absence of evidence is refusal. A missing backup, an unreadable disk figure
  or an unclassifiable record blocks the run rather than being assumed benign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from apps.core.demo_seed import PRODUCTION_ENVIRONMENTS, resolved_environment

#: Capability required to designate a demo tenant or approve a production run.
PLATFORM_OWNER_CAPABILITY = "platform.demo.govern"

#: How long a Platform Owner approval stays usable.
DEFAULT_APPROVAL_TTL = timedelta(hours=4)


@dataclass
class GateResult:
    """Outcome of the gate battery. Fails closed: any unmet condition blocks."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def require(self, condition: bool, description: str) -> None:
        (self.passed if condition else self.failed).append(description)

    @property
    def ok(self) -> bool:
        return not self.failed

    def raise_if_blocked(self) -> None:
        if self.failed:
            lines = "\n".join(f"  - {f}" for f in self.failed)
            raise CommandError(
                "Demo seed refused. Unmet conditions:\n"
                f"{lines}\n\n"
                f"Satisfied: {len(self.passed)}. Every condition must hold; the "
                "engine fails closed."
            )


def is_production() -> bool:
    return resolved_environment() in PRODUCTION_ENVIRONMENTS


def check_tenant_identity(
    tenant, *, confirm_slug: str | None, confirm_id: str | None, confirm_name: str | None
) -> GateResult:
    """The tenant must be a designated demo tenant, identified three ways.

    Requiring id, slug and name together is deliberate. A slug is easy to
    mistype into a different tenant; all three matching by accident is not a
    realistic failure mode.
    """
    result = GateResult()
    result.require(bool(tenant), "tenant resolved")
    if not tenant:
        return result

    result.require(
        tenant.is_demo,
        f"tenant '{tenant.slug}' is designated a demo tenant (is_demo=True). "
        "Use designate_demo_tenant to designate it.",
    )
    if confirm_slug is not None:
        result.require(
            tenant.slug == confirm_slug,
            f"--confirm-tenant-slug matches ({confirm_slug!r} vs {tenant.slug!r})",
        )
    if confirm_id is not None:
        result.require(
            str(tenant.id) == str(confirm_id),
            "--confirm-tenant-id matches the resolved tenant",
        )
    if confirm_name is not None:
        result.require(
            tenant.name == confirm_name,
            f"--confirm-tenant-name matches ({confirm_name!r} vs {tenant.name!r})",
        )
    return result


def check_external_side_effects() -> GateResult:
    """Nothing may leave the building during a seed."""
    result = GateResult()

    notifications_live = bool(getattr(settings, "DAWATRACE_NOTIFICATIONS_ENABLED", False))
    result.require(
        not notifications_live,
        "external notification sending is disabled (DAWATRACE_NOTIFICATIONS_ENABLED)",
    )

    fhir_writes = bool(getattr(settings, "FHIR_WRITE_INTERACTIONS_ENABLED", False))
    result.require(not fhir_writes, "outbound FHIR write interactions are disabled")

    return result


def check_provider_credentials() -> GateResult:
    """Refuse if a live national-integration credential could be called.

    Seeding must never cause a real request to DHA, PPB, HWR or an insurer.
    """
    result = GateResult()
    live = []
    for name in (
        "DAWATRACE_DHA_HIE_CLIENT_SECRET",
        "DAWATRACE_DHA_HWR_CLIENT_SECRET",
        "DAWATRACE_PPB_API_KEY",
        "DAWATRACE_SHA_CLIENT_SECRET",
    ):
        if str(getattr(settings, name, "") or "").strip():
            live.append(name)
    result.require(
        not live,
        "no live national-integration credentials configured"
        + (f" (found: {', '.join(live)})" if live else ""),
    )
    return result


def check_production_exception(
    *,
    tenant,
    allow_production_demo_seed: bool,
    approval,
    manifest_digest: str,
    backup_present: bool,
    capacity_ok: bool,
    data_classification: str,
) -> GateResult:
    """The narrow exception permitting a production run.

    Only reached when the environment is production. Every condition is
    independent; none implies another.
    """
    result = GateResult()

    result.require(
        allow_production_demo_seed,
        "--allow-production-demo-seed supplied (--allow-demo-seed alone never "
        "permits a production run)",
    )
    result.require(tenant is not None and tenant.is_demo, "tenant is a designated demo tenant")

    if approval is None:
        result.require(False, "a Platform Owner approval record exists for this plan")
    else:
        usable, why = approval.is_usable(now=timezone.now(), manifest_digest=manifest_digest)
        result.require(usable, f"Platform Owner approval is usable ({why or 'valid'})")
        result.require(
            approval.approved_by_id is not None
            and approval.approved_by_id != approval.requested_by_id,
            "approval was granted by someone other than the requester",
        )

    result.require(backup_present, "a recent database backup is recorded")
    result.require(capacity_ok, "disk and database capacity checks pass")
    result.require(
        data_classification in {"EMPTY_SAFE_TO_SEED", "DEMO_DATA_PRESENT"},
        f"existing tenant data is classified safe (got {data_classification})",
    )
    return result


def evaluate_all(
    *,
    tenant,
    allow_demo_seed: bool,
    allow_production_demo_seed: bool = False,
    confirm_slug: str | None = None,
    confirm_id: str | None = None,
    confirm_name: str | None = None,
    approval=None,
    manifest_digest: str = "",
    backup_present: bool = False,
    capacity_ok: bool = False,
    data_classification: str = "UNCLASSIFIED_DATA_PRESENT",
) -> GateResult:
    """Run every gate and return the combined result."""
    combined = GateResult()

    for partial in (
        check_tenant_identity(
            tenant, confirm_slug=confirm_slug, confirm_id=confirm_id, confirm_name=confirm_name
        ),
        check_external_side_effects(),
        check_provider_credentials(),
    ):
        combined.passed.extend(partial.passed)
        combined.failed.extend(partial.failed)

    if is_production():
        production = check_production_exception(
            tenant=tenant,
            allow_production_demo_seed=allow_production_demo_seed,
            approval=approval,
            manifest_digest=manifest_digest,
            backup_present=backup_present,
            capacity_ok=capacity_ok,
            data_classification=data_classification,
        )
        combined.passed.extend(production.passed)
        combined.failed.extend(production.failed)
    else:
        combined.require(
            allow_demo_seed or bool(getattr(settings, "DEBUG", False)),
            "--allow-demo-seed supplied, or DEBUG is on",
        )

    return combined
