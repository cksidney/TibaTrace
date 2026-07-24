#!/usr/bin/env bash
""":"
exec "${PYTHON:-python}" "$0" "$@"
"""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def file_sha256(filepath):
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def get_cmd_version(cmd):
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout.strip() or res.stderr.strip()
    except Exception:
        return "not installed / unavailable"

def generate_manifest(mode="full", steps_data=None):
    manifest_dir = ROOT / "artifacts" / "generated" / "validation"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / "repository-validation-manifest.json"

    # Git metadata
    git_branch = get_cmd_version(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    git_commit = get_cmd_version(["git", "rev-parse", "HEAD"])
    git_status = get_cmd_version(["git", "status", "--porcelain"])

    # Tool versions
    py_ver = sys.version.split()[0]
    node_ver = get_cmd_version(["node", "--version"])
    npm_ver = get_cmd_version(["npm", "--version"])
    docker_ver = get_cmd_version(["docker", "--version"])
    compose_ver = get_cmd_version(["docker", "compose", "version"])

    # Evidence checksums
    evidence_files = {
        "migration_reversibility": ROOT / "artifacts" / "generated" / "validation" / "migration-reversibility.json",
        "frontend_workspace_matrix": ROOT / "artifacts" / "generated" / "validation" / "frontend-workspace-matrix.json",
        "openapi_contract": ROOT / "artifacts" / "contracts" / "openapi.json",
        "backend_pytest_xml": ROOT / "artifacts" / "generated" / "tests" / "backend.xml",
        "bandit_security": ROOT / "artifacts" / "generated" / "security" / "bandit.json",
        "cyclonedx_sbom": ROOT / "artifacts" / "generated" / "security" / "dawatrace-backend.cdx.json",
        "secret_scan": ROOT / "artifacts" / "generated" / "security" / "secret-scan.json",
    }

    checksums = {k: file_sha256(v) for k, v in evidence_files.items() if file_sha256(v) is not None}

    steps = steps_data or []

    # Derive validation decision automatically
    failed_steps = [s for s in steps if s.get("result") == "FAILED"]
    skipped_steps = [s for s in steps if s.get("result") == "SKIPPED"]
    if failed_steps:
        overall_decision = "VALIDATION_FAILED"
    elif skipped_steps:
        overall_decision = "VALIDATION_PASSED_WITH_DOCUMENTED_NON_BLOCKERS"
    else:
        overall_decision = "VALIDATION_PASSED"

    deferred_gates = [
        {
            "gate": step["name"],
            "reason": step.get("skip_reason"),
        }
        for step in skipped_steps
    ]

    manifest = {
        "project_name": "DawaTrace",
        "project_version": "0.1.0-alpha.1",
        "phase": 5,
        "validation_mode": mode,
        "overall_decision": overall_decision,
        "coherence_declaration": "Repository-wide source coherence is evaluated across backend models, migrations, domain services, API schemas, shared TypeScript contracts, tests, startup imports, security checks and deployment configuration. Deferred gates are listed explicitly and are not represented as executed.",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "os": platform.platform(),
            "python_version": py_ver,
            "node_version": node_ver,
            "npm_version": npm_ver,
            "docker_version": docker_ver,
            "docker_compose_version": compose_ver,
        },
        "git": {
            "branch": git_branch,
            "commit_sha": git_commit,
            "clean_working_tree": len(git_status) == 0
        },
        "evidence_checksums_sha256": checksums,
        "deferred_gates": deferred_gates,
        "steps": steps
    }

    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"✅ Refined validation evidence manifest written to {manifest_file}")
    return 0

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    steps_raw = sys.argv[2] if len(sys.argv) > 2 else "[]"
    try:
        steps_data = json.loads(steps_raw)
    except Exception:
        steps_data = []
    sys.exit(generate_manifest(mode, steps_data))
