"""Fail closed on incomplete, wrong-source or high/critical runtime scans."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def validate_scan(report: dict, *, image: str, source_sha: str, backend: bool) -> dict:
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("A complete Trivy container-image report is required.")
    if report.get("ArtifactName") != image:
        raise ValueError("The scan does not describe the expected image reference.")
    metadata = report.get("Metadata", {})
    os_info = metadata.get("OS", {})
    if os_info.get("Family") not in {"alpine", "debian"} or not os_info.get("Name"):
        raise ValueError("Unsupported or missing OS inventory is not a passing scan.")
    if os_info.get("EOSL") or os_info.get("EOL"):
        raise ValueError("An end-of-support runtime cannot pass the release gate.")
    config = metadata.get("ImageConfig", {})
    if config.get("architecture") != "amd64" or config.get("os") != "linux":
        raise ValueError("Scan architecture must match the Linux amd64 release.")
    labels = config.get("config", {}).get("Labels", {})
    if labels.get("org.opencontainers.image.revision") != source_sha:
        raise ValueError("The scan image revision does not match the release source.")
    results = report.get("Results", [])
    if not any(row.get("Class") == "os-pkgs" and row.get("Packages") for row in results):
        raise ValueError("A scanned OS package inventory is required.")
    python_packages = {
        package.get("Name", "").lower()
        for row in results if row.get("Type") == "python-pkg"
        for package in row.get("Packages", [])
    }
    if backend and not {"django", "djangorestframework", "cryptography"} <= python_packages:
        raise ValueError("Backend application dependency inventory is incomplete.")
    vulnerabilities = [entry for row in results for entry in row.get("Vulnerabilities", [])]
    allowed = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
    if any(entry.get("Severity") not in allowed for entry in vulnerabilities):
        raise ValueError("Missing or invalid vulnerability severity cannot pass.")
    blocked = [entry for entry in vulnerabilities if entry["Severity"] in {"HIGH", "CRITICAL"}]
    if blocked:
        details = ", ".join(f"{entry.get('PkgName')}:{entry.get('VulnerabilityID')}:{entry['Severity']}" for entry in blocked[:20])
        raise ValueError(f"High/critical vulnerabilities remain (including unfixed findings): {details}")
    return {
        "image": image, "source_sha": source_sha, "scanner": report.get("Trivy", {}),
        "os": os_info, "policy": "no HIGH/CRITICAL findings; no suppression or ignore-unfixed",
        "severity_counts": dict(Counter(entry["Severity"] for entry in vulnerabilities)),
        "python_package_count": len(python_packages), "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--backend", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_scan(json.loads(args.report.read_text()), image=args.image, source_sha=args.source_sha, backend=args.backend)
    except (ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Container scan gate refused: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
