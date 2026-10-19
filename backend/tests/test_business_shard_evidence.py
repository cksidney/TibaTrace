"""A partial, failed or mixed-source test run must never unlock image publication."""

import json
import runpy
from pathlib import Path

import pytest

verify = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/verify_business_shards.py"))["verify"]


@pytest.fixture
def coverage_evidence(tmp_path):
    nodes = [f"tests/example.py::test_{index}" for index in range(5)]
    for index in range(2):
        selected = nodes[index::2]
        data = {
            "source_sha": "fixed-release-source",
            "database": "postgresql",
            "index": index,
            "count": 2,
            "all_nodes": nodes,
            "selected_nodes": selected,
            "report": f"report-{index}.xml",
        }
        (tmp_path / f"{index}-selection.json").write_text(json.dumps(data))
        (tmp_path / data["report"]).write_text(
            f'<testsuites><testsuite tests="{len(selected)}" errors="0" failures="0">'
            + "<testcase/>" * len(selected) + "</testsuite></testsuites>"
        )
    return tmp_path


def check(root):
    return verify(root, database="postgresql", expected_sha="fixed-release-source", shards=2)


def test_complete_nonuniform_partitions_are_accepted(coverage_evidence):
    assert check(coverage_evidence) == 5


@pytest.mark.parametrize("field,value", [
    ("source_sha", "different-source"), ("count", 3), ("index", 0),
    ("all_nodes", ["other-collection"]), ("selected_nodes", ["omitted-and-duplicated"]),
    ("database", "sqlite"), ("report", "../unrelated.xml"),
])
def test_mixed_or_incomplete_partitions_cannot_pass(coverage_evidence, field, value):
    target = coverage_evidence / "1-selection.json"
    data = json.loads(target.read_text())
    data[field] = value
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        check(coverage_evidence)


def test_missing_partition_cannot_pass(coverage_evidence):
    (coverage_evidence / "1-selection.json").unlink()
    with pytest.raises(ValueError, match="Missing"):
        check(coverage_evidence)


@pytest.mark.parametrize("report", [
    '<testsuite tests="2" failures="1"><testcase/><testcase/></testsuite>',
    '<testsuite tests="2" errors="1"><testcase/><testcase/></testsuite>',
    '<testsuite tests="1"><testcase/></testsuite>',
    '<testsuite tests="2"><testcase/></testsuite>',
])
def test_failed_or_truncated_reports_cannot_pass(coverage_evidence, report):
    (coverage_evidence / "report-1.xml").write_text(report)
    with pytest.raises(ValueError):
        check(coverage_evidence)
