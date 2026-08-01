#!/usr/bin/env python3
"""Structured migration inventory for a release, derived from the Django graph.

Release evidence once reported ``"migrations": []`` for a release that carries
one, because the generator scraped ``migrate --plan`` text and the command had
failed. Text scraping is the wrong source: it needs a database, it is easy to
misparse, and a failure looks identical to "nothing to do".

This reads the migration classes themselves through Django's loader, so the
operation list is what will actually run. It is deliberately fail-closed --
every unexpected condition raises rather than emitting an empty inventory.

Run inside the release image, with the set of migration files introduced since
the deployed baseline supplied by the caller:

    TIBATRACE_NEW_MIGRATION_FILES="backend/apps/platform/migrations/0002_x.py" \\
    python scripts/migration_evidence.py --output MIGRATIONS.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: Operations that can destroy data. Presence demands an explicit, reviewed
#: declaration before a release ships.
DESTRUCTIVE_OPERATIONS = frozenset(
    {
        "DeleteModel",
        "RemoveField",
        "RenameModel",
        "RenameField",
        "AlterModelTable",
        "RemoveConstraint",
        "RemoveIndex",
    }
)

#: Arbitrary Python against production rows.
DATA_MIGRATION_OPERATIONS = frozenset({"RunPython"})

#: Raw SQL, which the operation inspector cannot reason about.
SQL_OPERATIONS = frozenset({"RunSQL"})


class EvidenceError(RuntimeError):
    """Raised for any condition that must fail the release rather than degrade."""


def _migration_key(path: str) -> tuple[str, str]:
    """('backend/apps/platform/migrations/0002_x.py') -> ('platform', '0002_x')."""

    parts = Path(path).parts
    try:
        migrations_at = len(parts) - 1 - list(reversed(parts)).index("migrations")
    except ValueError as exc:
        raise EvidenceError(f"not a migration path: {path}") from exc
    app_label = parts[migrations_at - 1]
    return app_label, Path(path).stem


def build_inventory(new_files: list[str]) -> list[dict]:
    import django

    django.setup()
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(None, ignore_no_migrations=True)

    inventory: list[dict] = []
    for source_path in sorted(new_files):
        app_label, name = _migration_key(source_path)
        migration = loader.disk_migrations.get((app_label, name))
        if migration is None:
            raise EvidenceError(
                f"{app_label}.{name} exists in the release source but Django's "
                "migration loader cannot see it; the inventory would be wrong"
            )

        operation_types = [type(op).__name__ for op in migration.operations]
        if not operation_types:
            raise EvidenceError(f"{app_label}.{name} declares no operations")

        destructive = sorted(set(operation_types) & DESTRUCTIVE_OPERATIONS)
        inventory.append(
            {
                "app": app_label,
                "migration": name,
                "operation_count": len(operation_types),
                "operation_types": operation_types,
                "reversible": bool(
                    all(getattr(op, "reversible", True) for op in migration.operations)
                ),
                "destructive": bool(destructive),
                "destructive_operations": destructive,
                "data_migration": bool(set(operation_types) & DATA_MIGRATION_OPERATIONS),
                "sql_operation": bool(set(operation_types) & SQL_OPERATIONS),
                "source_path": source_path,
            }
        )
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="Destination path, or '-' for stdout.")
    parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Acknowledge that this release intentionally ships a destructive migration.",
    )
    args = parser.parse_args()

    raw = os.environ.get("TIBATRACE_NEW_MIGRATION_FILES")
    if raw is None:
        raise EvidenceError(
            "TIBATRACE_NEW_MIGRATION_FILES is unset. The caller must compute the "
            "migrations introduced since the deployment baseline; defaulting to "
            "an empty list is how a release reports no migrations when it has one."
        )

    new_files = [line.strip() for line in raw.splitlines() if line.strip()]
    inventory = build_inventory(new_files)

    destructive = [m for m in inventory if m["destructive"]]
    if destructive and not args.allow_destructive:
        names = ", ".join(f"{m['app']}.{m['migration']}" for m in destructive)
        raise EvidenceError(
            f"destructive migration(s) present without an explicit declaration: {names}"
        )

    payload = json.dumps(inventory, indent=2) + "\n"
    if str(args.output) == "-":
        # Written to stdout so the caller can redirect it. The container runs
        # as a non-root user and cannot write into a mounted host directory
        # owned by the CI runner.
        sys.stdout.write(payload)
    else:
        args.output.write_text(payload, encoding="utf-8")

    # Progress goes to stderr so it never contaminates the JSON on stdout.
    print(f"{len(inventory)} migration(s) recorded", file=sys.stderr)
    for m in inventory:
        print(f"  {m['app']}.{m['migration']}: {', '.join(m['operation_types'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EvidenceError as exc:
        print(f"migration evidence error: {exc}", file=sys.stderr)
        sys.exit(1)
