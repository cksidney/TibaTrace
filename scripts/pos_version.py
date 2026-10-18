"""POS release versions use one digit each for minor and patch, then carry."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.([0-9])\.([0-9])")


def validate_version(version: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        raise ValueError("POS versions require a numeric major and single-digit minor/patch: 1.0.9 → 1.1.0.")
    return tuple(int(part) for part in match.groups())


def next_version(version: str) -> str:
    major, minor, patch = validate_version(version)
    patch += 1
    if patch == 10:
        minor, patch = minor + 1, 0
    if minor == 10:
        major, minor = major + 1, 0
    return f"{major}.{minor}.{patch}"


def check_repository(root: Path, platforms: list[str], tag: str = "") -> None:
    lock = json.loads((root / "package-lock.json").read_text())
    for platform in platforms:
        path = f"apps/pos-{platform}"
        package = json.loads((root / path / "package.json").read_text())
        version, build = package["version"], package.get("tibatraceBuildNumber")
        validate_version(version)
        if type(build) is not int or build < 1:
            raise ValueError(f"{platform}: a positive integer tibatraceBuildNumber is required.")
        if lock["packages"][path]["version"] != version:
            raise ValueError(f"{platform}: package-lock.json version differs from package.json.")
        prefix = f"pos-{platform}-v"
        if tag.startswith(prefix) and tag != prefix + version:
            raise ValueError(f"{platform}: release tag differs from package version.")
        print(f"{platform}: version {version}, build {build}; next version {next_version(version)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["windows", "android", "all"], default="all")
    parser.add_argument("--next", metavar="VERSION", help="Print the next version without editing files.")
    args = parser.parse_args()
    try:
        if args.next:
            print(next_version(args.next))
        else:
            check_repository(Path(__file__).resolve().parents[1],
                             ["windows", "android"] if args.platform == "all" else [args.platform],
                             os.environ.get("GITHUB_REF_NAME", ""))
    except (KeyError, ValueError) as exc:
        parser.exit(1, f"Version validation failed: {exc}\n")


if __name__ == "__main__":
    main()
