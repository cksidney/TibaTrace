#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export DawaTrace database schema evidence.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.test")

    import django

    django.setup()

    from django.apps import apps
    from django.db import connection

    dawatrace_tables = {
        model._meta.db_table: model._meta.label
        for model in apps.get_models()
        if model._meta.app_label not in {"admin", "auth", "contenttypes", "sessions"}
    }
    tables = {}
    with connection.cursor() as cursor:
        installed = set(connection.introspection.table_names(cursor))
        for table, model_label in sorted(dawatrace_tables.items()):
            if table not in installed:
                continue
            constraints = connection.introspection.get_constraints(cursor, table)
            tables[table] = {
                "model": model_label,
                "constraints": {
                    name: {
                        "columns": value.get("columns", []),
                        "primary_key": bool(value.get("primary_key")),
                        "unique": bool(value.get("unique")),
                        "foreign_key": value.get("foreign_key"),
                        "check": bool(value.get("check")),
                        "index": bool(value.get("index")),
                    }
                    for name, value in sorted(constraints.items())
                },
            }

    payload = {
        "product": "DawaTrace",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_vendor": connection.vendor,
        "dawatrace_table_count": len(tables),
        "tables": tables,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(tables)} DawaTrace tables to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
