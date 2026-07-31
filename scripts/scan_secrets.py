#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe-live-key": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|secret[_-]?key|access[_-]?token)\b\s*[:=]\s*['\"]([^'\"]{12,})['\"]"
    ),
    # A constant such as DEMO_PASSWORD = "...". The assigned-secret rule cannot
    # see these: \bpassword never matches inside DEMO_PASSWORD, because the
    # underscore is a word character. Any length is reported -- a short
    # credential is a worse finding, not an exempt one.
    # Constants whose name ends in _ENV_VAR, _VAR, _NAME, _HEADER or _FIELD
    # are excluded: they name where a credential lives rather than holding one,
    # so DEMO_PASSWORD_ENV_VAR = "DAWATRACE_DEMO_SEED_PASSWORD" is not a finding.
    "password-constant": re.compile(
        r"(?i)^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY)[A-Z0-9_]*"
        r"(?<!_ENV_VAR)(?<!_VAR)(?<!_NAME)(?<!_HEADER)(?<!_FIELD)"
        r"\s*=\s*['\"]([^'\"]+)['\"]"
    ),
    # set_password("literal") -- a credential written directly into an account.
    "set-password-literal": re.compile(r"\.set_password\(\s*['\"][^'\"]+['\"]\s*\)"),
    # create_user(..., password="literal") and its superuser variant.
    "create-user-password-literal": re.compile(
        r"(?i)\bcreate_(?:user|superuser)\s*\([^)]*\bpassword\s*=\s*['\"][^'\"]+['\"]"
    ),
    # Printing a credential alongside the account it belongs to.
    "printed-credential": re.compile(
        r"(?i)(?:username|user|login|account)\s*[:/]\s*.*\{[^}]*(?:password|passwd|secret)[^}]*\}"
    ),
    # A password prefilled into markup: <input type="password" ... value="...">.
    # Anything shipped this way reaches every browser that loads the page, so
    # any non-empty value is a finding regardless of length.
    "prefilled-password-input": re.compile(
        r"(?i)<input[^>]*type\s*=\s*['\"]password['\"][^>]*\bvalue\s*=\s*['\"][^'\"]+['\"]"
    ),
    # The same input with the attributes written the other way round.
    "prefilled-password-input-reversed": re.compile(
        r"(?i)<input[^>]*\bvalue\s*=\s*['\"][^'\"]+['\"][^>]*type\s*=\s*['\"]password['\"]"
    ),
}

#: Rules exempted inside test modules. Test fixtures legitimately construct
#: accounts with fixed passwords; flagging every one would train reviewers to
#: ignore the scanner. Exemption is by location only -- a test-shaped name
#: outside a tests package is still scanned.
TEST_EXEMPT_RULES = {
    "assigned-secret",
    "password-constant",
    "set-password-literal",
    "create-user-password-literal",
    "printed-credential",
}
PLACEHOLDER_MARKERS = {
    "example",
    "fixture",
    "local-only",
    "not-a-secret",
    "replace",
    "strong-test-password",
    "test-password",
    "test-only",
    "unsafe-development",
}
TEXT_SUFFIXES = {
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "dist", "node_modules", "staticfiles"}


def scan(root: Path) -> list[dict]:
    findings = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root)
        if relative.parts[:2] == ("artifacts", "generated"):
            continue
        if path.name not in {".env.example", ".env.test", "Dockerfile"} and path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        # This scanner necessarily contains strings shaped like the credentials
        # it hunts for, so it does not scan its own rule definitions.
        if relative == Path("scripts/scan_secrets.py"):
            continue
        is_test_fixture = "tests" in relative.parts or relative.name.startswith("test_")
        for line_number, line in enumerate(lines, 1):
            lowered = line.casefold()
            for rule, pattern in RULES.items():
                if not pattern.search(line):
                    continue
                if rule in TEST_EXEMPT_RULES and is_test_fixture:
                    continue
                if rule in TEST_EXEMPT_RULES and any(marker in lowered for marker in PLACEHOLDER_MARKERS):
                    continue
                findings.append({"path": str(relative), "line": line_number, "rule": rule})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan DawaTrace source for common committed-secret formats.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    findings = scan(args.root.resolve())
    payload = {
        "product": "DawaTrace",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanner": "DawaTrace local regex baseline",
        "finding_count": len(findings),
        "findings": findings,
        "limitations": "This local baseline does not replace history-aware entropy scanning in CI.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"finding_count": len(findings), "output": str(args.output)}))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
