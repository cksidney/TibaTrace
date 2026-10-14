"""Release security evidence must identify the whole exact runtime image."""
import copy
from pathlib import Path

import pytest


@pytest.fixture
def scanner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    from validate_container_scan import validate_scan
    return validate_scan


@pytest.fixture
def report():
    return {
        "SchemaVersion": 2, "ArtifactType": "container_image", "ArtifactName": "release:exact",
        "Trivy": {"Version": "0.75.0"},
        "Metadata": {
            "OS": {"Family": "alpine", "Name": "3.24.2"},
            "ImageConfig": {"architecture": "amd64", "os": "linux", "config": {
                "Labels": {"org.opencontainers.image.revision": "source-exact"},
            }},
        },
        "Results": [
            {"Class": "os-pkgs", "Type": "alpine", "Packages": [{"Name": "musl"}], "Vulnerabilities": []},
            {"Class": "lang-pkgs", "Type": "python-pkg", "Packages": [
                {"Name": "Django"}, {"Name": "djangorestframework"}, {"Name": "cryptography"},
            ], "Vulnerabilities": []},
        ],
    }


def check(scanner, report, backend=True):
    return scanner(report, image="release:exact", source_sha="source-exact", backend=backend)


def test_complete_scan_preserves_visible_nonblocking_findings(scanner, report):
    report["Results"][0]["Vulnerabilities"] = [{"Severity": "MEDIUM", "PkgName": "package", "VulnerabilityID": "CVE-test"}]
    result = check(scanner, report)
    assert result["status"] == "PASS" and result["severity_counts"] == {"MEDIUM": 1}
    assert result["source_sha"] == "source-exact" and result["python_package_count"] == 3


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL"])
def test_high_critical_findings_block_even_without_a_published_fix(scanner, report, severity):
    report["Results"][0]["Vulnerabilities"] = [{"Severity": severity, "PkgName": "package", "VulnerabilityID": "CVE-unfixed"}]
    with pytest.raises(ValueError, match="High/critical"):
        check(scanner, report)


@pytest.mark.parametrize("invalid", ["reference", "revision", "architecture", "unsupported-os", "missing-os-packages", "missing-application", "eol", "invalid-severity"])
def test_wrong_source_or_incomplete_scan_cannot_pass(scanner, report, invalid):
    changed = copy.deepcopy(report)
    if invalid == "reference":
        changed["ArtifactName"] = "another:image"
    elif invalid == "revision":
        changed["Metadata"]["ImageConfig"]["config"]["Labels"] = {}
    elif invalid == "architecture":
        changed["Metadata"]["ImageConfig"]["architecture"] = "arm64"
    elif invalid == "unsupported-os":
        changed["Metadata"]["OS"]["Family"] = "none"
    elif invalid == "missing-os-packages":
        changed["Results"][0]["Packages"] = []
    elif invalid == "missing-application":
        changed["Results"][1]["Packages"] = []
    elif invalid == "eol":
        changed["Metadata"]["OS"]["EOSL"] = True
    elif invalid == "invalid-severity":
        changed["Results"][0]["Vulnerabilities"] = [{"PkgName": "package"}]
    with pytest.raises(ValueError):
        check(scanner, changed)


def test_static_hq_does_not_need_a_fabricated_python_inventory(scanner, report):
    report["Results"] = report["Results"][:1]
    assert check(scanner, report, backend=False)["status"] == "PASS"
