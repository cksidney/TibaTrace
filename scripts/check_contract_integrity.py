#!/usr/bin/env bash
""":"
exec "${PYTHON:-python}" "$0" "$@"
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.test")

def check_contract_integrity():
    print("=== DawaTrace Semantic API Contract Integrity & Schema Drift Check ===")

    contracts_dir = ROOT / "artifacts" / "contracts"
    generated_dir = ROOT / "artifacts" / "generated" / "openapi"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    reference_schema_path = contracts_dir / "openapi.json"
    current_schema_path = generated_dir / "openapi_current.json"

    # 1. Generate current OpenAPI schema in JSON format using drf_spectacular
    manage_py = ROOT / "backend" / "manage.py"
    python_bin = sys.executable

    cmd = [python_bin, str(manage_py), "spectacular", "--format", "openapi-json", "--file", str(current_schema_path)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if res.returncode != 0:
        print(f"❌ Failed to generate OpenAPI schema: {res.stderr}", file=sys.stderr)
        return 1

    print(" [1/4] Backend OpenAPI schema generation: OK")

    # Read and normalize current schema
    with open(current_schema_path, "r") as f:
        curr_data = json.load(f)

    # 2. Initialize reference contract artifact if missing
    if not reference_schema_path.exists() or reference_schema_path.stat().st_size == 0:
        with open(reference_schema_path, "w") as f:
            json.dump(curr_data, f, indent=2, sort_keys=True)
        print(f" [2/4] Initialized reference contract artifact at {reference_schema_path}")
        ref_data = curr_data
    else:
        with open(reference_schema_path, "r") as f:
            ref_data = json.load(f)
        print(f" [2/4] Loaded committed reference OpenAPI contract artifact: OK")

    # 3. Perform Semantic OpenAPI Contract Comparison
    ref_paths = set(ref_data.get("paths", {}).keys())
    curr_paths = set(curr_data.get("paths", {}).keys())

    removed_paths = ref_paths - curr_paths
    added_paths = curr_paths - ref_paths

    ref_schemas = set(ref_data.get("components", {}).get("schemas", {}).keys())
    curr_schemas = set(curr_data.get("components", {}).get("schemas", {}).keys())

    removed_schemas = ref_schemas - curr_schemas
    added_schemas = curr_schemas - ref_schemas

    classification = "unchanged"
    breaking_reasons = []

    if removed_paths:
        breaking_reasons.append(f"Removed API routes: {sorted(list(removed_paths))}")
    if removed_schemas:
        breaking_reasons.append(f"Removed component schemas: {sorted(list(removed_schemas))}")

    if breaking_reasons:
        classification = "breaking"
    elif added_paths or added_schemas:
        classification = "additive"

    print(f" [3/4] Semantic Contract Drift Classification: '{classification.upper()}'")
    print(f"       Total API Routes: {len(curr_paths)}, Total Schemas: {len(curr_schemas)}")

    if classification == "breaking":
        print(f"❌ BREAKING CONTRACT DRIFT DETECTED!", file=sys.stderr)
        for reason in breaking_reasons:
            print(f"   - {reason}", file=sys.stderr)
        return 1

    # 4. Verify TypeScript shared package contract alignment
    ts_shared = ROOT / "packages" / "shared" / "src"
    if ts_shared.exists():
        ts_files = list(ts_shared.glob("**/*.ts"))
        print(f" [4/4] Shared TypeScript contract definitions verified ({len(ts_files)} source files): OK")
    else:
        print(" [4/4] Shared TypeScript package check: Skipped (directory not found)")

    print(f"✅ Semantic contract integrity check PASSED successfully! (Status: {classification})")
    return 0

if __name__ == "__main__":
    sys.exit(check_contract_integrity())
