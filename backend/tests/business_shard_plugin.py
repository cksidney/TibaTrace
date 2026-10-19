"""Partition the full collected suite; emit independently verifiable coverage."""

import json
import os
import subprocess
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    count = int(os.environ.get("BUSINESS_SHARD_COUNT", "1"))
    index = int(os.environ.get("BUSINESS_SHARD_INDEX", "0"))
    if not 0 <= index < count:
        raise pytest.UsageError("Require 0 <= BUSINESS_SHARD_INDEX < BUSINESS_SHARD_COUNT.")
    all_nodes = [item.nodeid for item in items]
    selected = [item for position, item in enumerate(items) if position % count == index]
    selected_ids = {item.nodeid for item in selected}
    if not selected or len(set(all_nodes)) != len(all_nodes):
        raise pytest.UsageError("Business suite selection must be nonempty and node IDs unique.")
    evidence = Path(os.environ["BUSINESS_SHARD_EVIDENCE"])
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "database": os.environ["BUSINESS_SHARD_DATABASE"],
        "index": index,
        "count": count,
        "all_nodes": all_nodes,
        "selected_nodes": [item.nodeid for item in selected],
        "report": os.environ["BUSINESS_SHARD_REPORT"],
    }, indent=2) + "\n")
    config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in selected_ids])
    items[:] = selected
