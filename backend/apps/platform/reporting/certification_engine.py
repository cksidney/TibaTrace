"""Phase 16 Certification Evidence Engine.

Generates structured compliance and certification evidence bundles for national health
system audits (DHA, PPB, HWR).

Bundle elements:
  - OpenAPI spec & checksum
  - Migration plan, evidence & drift check
  - Test results, coverage & quality metrics
  - Bandit security audit findings
  - Ruff lint metrics
  - SBOM & SLSA provenance metadata
  - Build & release manifest
  - Platform & Provider readiness matrices

Metadata tagged on every evidence item:
  timestamp, commit_sha, version, environment, operator, truth_label
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import zipfile
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
TRUTH_LABEL = "MANUAL_INTERNAL_VERIFICATION"
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def get_current_commit_sha() -> str:
    """Resolve the build commit without launching a child process.

    Release builders should provide ``DAWATRACE_COMMIT_SHA`` (or ``GITHUB_SHA``).
    The loose/packed git-reference fallback keeps local evidence useful while
    avoiding executable-path and command-injection risk in a web request.
    """
    for variable in ("DAWATRACE_COMMIT_SHA", "GITHUB_SHA"):
        value = os.environ.get(variable, "").strip().lower()
        if _COMMIT_SHA_RE.fullmatch(value):
            return value

    git_entry = REPO_ROOT / ".git"
    try:
        if git_entry.is_file():
            marker = git_entry.read_text(encoding="utf-8").strip()
            if not marker.startswith("gitdir: "):
                return "UNKNOWN_COMMIT_SHA"
            git_dir = (REPO_ROOT / marker.removeprefix("gitdir: ")).resolve()
        else:
            git_dir = git_entry

        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if _COMMIT_SHA_RE.fullmatch(head.lower()):
            return head.lower()
        if not head.startswith("ref: "):
            return "UNKNOWN_COMMIT_SHA"

        ref_name = head.removeprefix("ref: ")
        loose_ref = git_dir / ref_name
        if loose_ref.is_file():
            value = loose_ref.read_text(encoding="utf-8").strip().lower()
            return value if _COMMIT_SHA_RE.fullmatch(value) else "UNKNOWN_COMMIT_SHA"

        packed_refs = git_dir / "packed-refs"
        if packed_refs.is_file():
            for line in packed_refs.read_text(encoding="utf-8").splitlines():
                if line.startswith(("#", "^")):
                    continue
                value, _, packed_ref_name = line.partition(" ")
                if packed_ref_name == ref_name and _COMMIT_SHA_RE.fullmatch(value.lower()):
                    return value.lower()
    except OSError:
        pass
    return "UNKNOWN_COMMIT_SHA"


class CertificationEvidenceGenerator:
    """Generates Phase 16 Certification Evidence Bundles."""

    @staticmethod
    def generate_evidence_package(operator_name: str = "System Automated Audit") -> dict[str, Any]:
        commit_sha = get_current_commit_sha()
        now_iso = timezone.now().isoformat()
        programme_version = str(getattr(settings, "DAWATRACE_VERSION", "UNKNOWN_VERSION"))

        meta = {
            "timestamp": now_iso,
            "commit_sha": commit_sha,
            "version": programme_version,
            "environment": getattr(settings, "ENVIRONMENT", "test"),
            "operator": operator_name,
            "truth_label": TRUTH_LABEL,
        }

        # 1. OpenAPI checksum
        openapi_path = BACKEND_ROOT / "openapi.yaml"
        openapi_sha256 = ""
        if openapi_path.exists():
            openapi_sha256 = hashlib.sha256(openapi_path.read_bytes()).hexdigest()

        def installed_version(package):
            try:
                return version(package)
            except PackageNotFoundError:
                return "NOT_INSTALLED"

        # Runtime inventory is not regulator approval or release test evidence.
        version_matrix = {
            **meta,
            "components": {
                "tibatrace_core": programme_version,
                "dha_fhir_ig": "NOT_VERIFIED",
                "kenya_digital_health_framework": "NOT_VERIFIED",
                "django_backend": installed_version("Django"),
                "python_runtime": platform.python_version(),
            },
        }

        # 3. Readiness matrix
        readiness_matrix = {
            **meta,
            "overall_readiness": None,
            "readiness_status": "NOT_CERTIFIED_EXTERNAL_ACCEPTANCE_PENDING",
            "matrices": {name: {"status": "EXTERNAL_ACCEPTANCE_NOT_VERIFIED", "score": None}
                         for name in ("dha_hie_readiness", "dha_hwr_readiness", "ppb_premises_readiness", "ppb_recalls_readiness")},
            "external_gates_pending": [
                "DHA OAuth production credentials",
                "PPB Premises Registry official API endpoint",
                "Official DHA sandbox clearance",
            ],
        }

        # 4. SBOM & SLSA Provenance
        sbom_provenance = {
            **meta,
            "slsa_level": "NOT_VERIFIED",
            "build_environment": "NOT_VERIFIED_BY_RUNTIME",
            "dependencies": {name: installed_version(name) for name in
                             ("Django", "djangorestframework", "drf-spectacular", "pytest", "bandit", "ruff")},
            "evidence_required": "Verify immutable CI release manifest, SBOM and build attestations for this commit.",
        }

        # 5. Quality & Security Evidence
        quality_evidence = {
            **meta,
            **{name: {"status": "NOT_VERIFIED", "source": "Commit-matched CI evidence required; runtime does not execute this check."}
               for name in ("backend_pytest", "nif_focused_tests", "shared_typescript_tests", "windows_pos_tests", "bandit_security", "migration_drift")},
        }

        package = {
            "metadata": meta,
            "openapi_checksum": {"file": "openapi.yaml", "sha256": openapi_sha256},
            "version_matrix": version_matrix,
            "readiness_matrix": readiness_matrix,
            "sbom_provenance": sbom_provenance,
            "quality_evidence": quality_evidence,
        }

        return package

    @staticmethod
    def export_evidence_zip(operator_name: str = "System Automated Audit") -> tuple[bytes, str]:
        """Export the full evidence package as a zip archive."""
        package = CertificationEvidenceGenerator.generate_evidence_package(operator_name)
        commit_sha = package["metadata"]["commit_sha"][:8]
        filename = f"tibatrace_certification_evidence_{commit_sha}.zip"

        mem = BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(package["metadata"], indent=2))
            zf.writestr("evidence_package.json", json.dumps(package, indent=2))
            zf.writestr("readiness_matrix.json", json.dumps(package["readiness_matrix"], indent=2))
            zf.writestr("version_matrix.json", json.dumps(package["version_matrix"], indent=2))
            zf.writestr("sbom_provenance.json", json.dumps(package["sbom_provenance"], indent=2))
            zf.writestr("quality_evidence.json", json.dumps(package["quality_evidence"], indent=2))

            # Include openapi.yaml if present
            openapi_path = BACKEND_ROOT / "openapi.yaml"
            if openapi_path.exists():
                zf.write(openapi_path, arcname="openapi.yaml")

        mem.seek(0)
        return mem.getvalue(), filename
