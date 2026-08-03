"""Deterministic dry-run manifest.

The manifest is the unit a Platform Owner approves. Its digest binds an
approval to one exact plan: same tenant, profile, version, seed and as-of date
produce the same digest, and any change to the plan produces a different one,
which invalidates the approval automatically.

Determinism is therefore a correctness property, not a nicety. The digest is
taken over a canonical JSON encoding with sorted keys, and every field in it is
either supplied by the caller or read from committed state -- nothing derived
from wall-clock time, hostname or row order participates.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, see _code_commit
from datetime import date
from typing import Any

from django.db.migrations.recorder import MigrationRecorder

from apps.platform.demo.profiles import SCENARIO_NAME, SCENARIO_VERSION, DemoProfile


def _code_commit() -> str:
    """Best-effort commit id. Absent in a container build; that is not fatal."""
    git = shutil.which("git")
    if not git:
        return ""
    try:
        # Fixed argv, absolute binary, no shell and no caller-supplied input.
        out = subprocess.run(  # nosec B603
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, shell=False
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _migration_head() -> str:
    """Latest applied migration, so a manifest cannot outlive its schema."""
    try:
        latest = MigrationRecorder.Migration.objects.order_by("-applied", "-id").first()
        return f"{latest.app}.{latest.name}" if latest else ""
    except Exception:
        return ""


def build_manifest(
    *,
    tenant,
    profile: DemoProfile,
    random_seed: int,
    as_of_date: date,
    environment: str,
    existing_counts: dict[str, int],
    data_classification: str,
    scale: str = "small",
) -> dict[str, Any]:
    """Assemble the manifest body. Excludes the digest, which covers it."""
    return {
        "scenario_name": SCENARIO_NAME,
        "scenario_version": SCENARIO_VERSION,
        "profile": profile.key,
        "profile_label": profile.label,
        "scale": scale,
        "random_seed": random_seed,
        "as_of_date": as_of_date.isoformat(),
        "months_of_history": profile.months_of_history,
        "tenant": {
            "id": str(tenant.id),
            "slug": tenant.slug,
            "name": tenant.name,
            "is_demo": bool(tenant.is_demo),
            "status": tenant.status,
        },
        "environment": environment,
        "planned_object_counts": dict(sorted(profile.counts.items())),
        "planned_total": profile.planned_total(),
        "existing_data_counts": dict(sorted(existing_counts.items())),
        "existing_data_classification": data_classification,
        "excluded_domains": dict(sorted(profile.excluded_domains.items())),
        "external_integrations_disabled": True,
        "notifications_suppressed": True,
        "expected_storage_growth_mb": _estimate_storage_mb(profile),
        "expected_runtime_minutes": _estimate_runtime_minutes(profile),
        "code_commit": _code_commit(),
        "migration_head": _migration_head(),
    }


def _estimate_storage_mb(profile: DemoProfile) -> int:
    """Rough growth estimate, deliberately conservative.

    Ledger and audit rows dominate. ~1 KB per row including indexes is the
    working assumption; the pilot exists partly to replace this with a measured
    figure.
    """
    rows = profile.planned_total()
    audit_multiplier = 3  # ledger + audit + projection rows per business object
    return max(1, (rows * audit_multiplier) // 1024)


def _estimate_runtime_minutes(profile: DemoProfile) -> int:
    """Rough runtime estimate.

    Generation is service-routed: every dispensing event walks a state machine,
    runs clinical screening and posts ledger entries. Assume ~20 objects/second
    sustained, which is optimistic for the clinical paths.
    """
    return max(1, profile.planned_total() // (20 * 60))


def digest_manifest(manifest: dict[str, Any]) -> str:
    """SHA-256 over a canonical encoding.

    ``sort_keys`` and a fixed separator make the encoding independent of dict
    insertion order, so two runs of the same plan agree.
    """
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def finalise(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest with its own digest attached."""
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return {**body, "manifest_sha256": digest_manifest(body)}
