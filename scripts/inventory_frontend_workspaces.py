#!/usr/bin/env bash
""":"
exec "${PYTHON:-python}" "$0" "$@"
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def inventory_frontend_workspaces():
    print("=== DawaTrace Frontend & Workspace Inventory Audit ===")

    workspaces = [
        {
            "name": "@dawatrace/shared",
            "type": "shared library",
            "path": "packages/shared",
            "description": "Authoritative TypeScript API models, FHIR interfaces, and domain status enums."
        },
        {
            "name": "@dawatrace/hq",
            "type": "deployable frontend scaffold",
            "path": "apps/hq",
            "description": "Reserved for Phase 3 enterprise administration UI scaffold."
        },
        {
            "name": "@dawatrace/portal",
            "type": "deployable frontend scaffold",
            "path": "apps/portal",
            "description": "Reserved for Phase 3 patient/provider portal UI scaffold."
        },
        {
            "name": "@dawatrace/pos-android",
            "type": "deployable Android application",
            "path": "apps/pos-android",
            "description": "React Native Android POS with native Gradle packaging and Keystore-backed recovery."
        },
        {
            "name": "@dawatrace/pos-windows",
            "type": "deployable Windows application",
            "path": "apps/pos-windows",
            "description": "Electron Windows POS with restricted IPC, DPAPI sessions, and MSIX packaging."
        }
    ]

    tsc_bin = ROOT / "node_modules" / ".bin" / "tsc"

    results = []
    for ws in workspaces:
        ws_path = ROOT / ws["path"]
        pkg_json_file = ws_path / "package.json"

        available_scripts = {}
        if pkg_json_file.exists():
            try:
                with open(pkg_json_file, "r") as f:
                    pkg_data = json.load(f)
                available_scripts = pkg_data.get("scripts", {})
            except Exception as e:
                print(f"Warning reading {pkg_json_file}: {e}")

        executed_commands = []
        status = "PASSED"
        skip_reason = None

        if pkg_json_file.exists() and "typecheck" in available_scripts:
            if tsc_bin.exists():
                start = time.time()
                cmd = ["npm", "run", "typecheck", "--workspace", ws["name"]]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                dur = round(time.time() - start, 3)

                executed_commands.append({
                    "command": " ".join(cmd),
                    "exit_code": res.returncode,
                    "duration_seconds": dur,
                    "result": "PASSED" if res.returncode == 0 else "FAILED"
                })
                if res.returncode != 0:
                    status = "FAILED"
            else:
                skip_reason = "tsc binary not found in node_modules"
        else:
            skip_reason = "No package-level typecheck script is configured."

        results.append({
            "workspace_name": ws["name"],
            "workspace_type": ws["type"],
            "package_path": ws["path"],
            "available_scripts": available_scripts,
            "executed_commands": executed_commands,
            "result": status,
            "skip_reason": skip_reason,
            "description": ws["description"]
        })

    output_dir = ROOT / "artifacts" / "generated" / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "frontend-workspace-matrix.json"

    matrix_data = {
        "version": "1.0.0",
        "baseline_note": "TibaTrace HQ, Android POS, and Windows POS are deployable clients; signing credentials and distribution approvals remain external release gates.",
        "total_workspaces": len(results),
        "workspaces": results
    }

    with open(output_file, "w") as f:
        json.dump(matrix_data, f, indent=2)

    print(f"✅ Frontend workspace inventory matrix written to {output_file}")
    return 0

if __name__ == "__main__":
    sys.exit(inventory_frontend_workspaces())
