import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pos_version.py"
spec = importlib.util.spec_from_file_location("pos_version_policy", SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize(("current", "expected"), [
    ("1.0.8", "1.0.9"), ("1.0.9", "1.1.0"), ("1.9.9", "2.0.0"), ("9.9.9", "10.0.0"),
])
def test_pos_version_carries_each_single_digit_segment(current, expected):
    assert policy.next_version(current) == expected


@pytest.mark.parametrize("version", ["1.0.10", "1.10.0", "01.0.0", "1.0.9.1", "1.0.9-rc1", "1.0"])
def test_pos_release_rejects_unsupported_version_formats(version):
    with pytest.raises(ValueError):
        policy.validate_version(version)


def test_current_pos_versions_and_lock_match_the_release_policy():
    policy.check_repository(SCRIPT.parent.parent, ["windows", "android"])


def test_pos_tag_must_match_the_package():
    with pytest.raises(ValueError, match="release tag"):
        policy.check_repository(SCRIPT.parent.parent, ["windows"], "pos-windows-v0.0.0")
