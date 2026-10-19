"""Fail release coverage unless all full-suite partitions succeeded exactly once."""

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def verify(root, *, database, expected_sha, shards):
    manifests = [
        (path, json.loads(path.read_text())) for path in Path(root).rglob("*selection.json")
    ]
    manifests = [(path, data) for path, data in manifests if data["database"] == database]
    if len(manifests) != shards or {data["index"] for _, data in manifests} != set(range(shards)):
        raise ValueError("Missing or duplicate business-suite partitions.")
    inventory = manifests[0][1]["all_nodes"]
    if not inventory or len(inventory) != len(set(inventory)):
        raise ValueError("Empty or duplicated full-suite inventory.")
    executed = Counter()
    for path, data in manifests:
        if data["source_sha"] != expected_sha or data["count"] != shards or data["all_nodes"] != inventory:
            raise ValueError("Source, partition count or collected suite differs between jobs.")
        selected = data["selected_nodes"]
        if selected != inventory[data["index"]::shards]:
            raise ValueError("Partition selection differs from the declared full suite.")
        report_name = data["report"]
        if Path(report_name).name != report_name:
            raise ValueError("Report must be a sibling artifact file.")
        report = ET.parse(path.with_name(report_name)).getroot()
        suites = [report] if report.tag == "testsuite" else list(report.iter("testsuite"))
        if not suites or any(int(suite.get(key, "0")) for suite in suites for key in ("errors", "failures")):
            raise ValueError("Business-suite report is absent or has failures/errors.")
        cases = [case for suite in suites for case in suite.findall("testcase")]
        if len(cases) != len(selected) or sum(int(suite.get("tests", "0")) for suite in suites) != len(selected):
            raise ValueError("Report does not account for every selected test.")
        executed.update(selected)
    if executed != Counter(inventory):
        raise ValueError("Full-suite coverage has omitted or duplicated tests.")
    return len(inventory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--database", required=True, choices=["sqlite", "postgresql"])
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--shards", required=True, type=int)
    args = parser.parse_args()
    total = verify(args.root, database=args.database, expected_sha=args.expected_sha, shards=args.shards)
    print(f"{args.database}: all {total} collected tests accounted for exactly once across {args.shards} passing jobs")
