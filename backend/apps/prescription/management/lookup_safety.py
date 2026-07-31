from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path

UUID_LOOKUP_KEYS = frozenset({"id", "pk", "uuid"})
TENANT_SCOPE_KEYS = frozenset({"tenant", "tenant_id"})
LOOKUP_METHODS = frozenset({"exclude", "filter", "get"})
ORM_MANAGERS = frozenset({"all_objects", "objects"})

# These records are intentionally shared platform reference data. Adding a model
# here requires an explicit review of its persistence and authorization policy.
EXPLICIT_GLOBAL_MODELS = frozenset(
    {
        "Medicine",
        "ClinicalKnowledgeRelease",
        "FHIRTerminologyVersion",
        "Tenant",
        # POS installers. Reviewed on 2026-07-27:
        #
        # Persistence -- the model has no tenant column by design. An installer
        # is one binary for every pharmacy, and scoping it per tenant would mean
        # storing the same 35 MB artefact once per customer.
        #
        # Authorization -- both endpoints require an authenticated HQ session,
        # only rows with is_published are exposed (an unpublished build answers
        # 404, not 403, so the endpoint does not report what exists), and the
        # artefact is handed out as a signed URL that expires in five minutes
        # rather than served from a stable path. Every download is audited.
        "PosRelease",
    }
)

# Per-call-site exemptions, narrower than EXPLICIT_GLOBAL_MODELS: each marks one
# lookup, on the line above it, rather than every lookup of a model. The value
# is the module the marker may appear in, so pasting the comment onto an
# unrelated lookup does not silence the audit; None means any module. Adding an
# entry requires the same explicit review.
REVIEWED_SITE_MARKERS: dict[str, str | None] = {
    # Re-reading a row by its own pk to prove it already exists before refusing
    # an update. Safe in any module: the pk being read is the record's own, so
    # the lookup cannot reach another tenant's data by construction.
    "# tenant-safety: immutable-existence-check": None,
    # Credential recovery, which is global by construction. Reviewed on
    # 2026-07-31, and confined to the password-reset view:
    #
    # Scope -- a password reset link is issued before any tenant context exists;
    # the signed uid is the only identifier available, so the lookup cannot be
    # tenant-qualified without changing the link format.
    #
    # Authorization -- resolving the row is not the access decision. The request
    # is rejected unless PasswordResetTokenGenerator.check_token succeeds, and
    # that token is bound to the user's pk, password hash and last_login, so it
    # cannot be replayed against a different user.
    "# tenant-safety: global-credential-recovery": "identity/api/session_views.py",
}


@dataclass(frozen=True)
class UnsafeLookup:
    path: str
    line: int
    model: str
    manager: str
    method: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _manager_call(node: ast.Call) -> tuple[str, str, str] | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in LOOKUP_METHODS:
        return None
    manager_node = node.func.value
    if not isinstance(manager_node, ast.Attribute) or manager_node.attr not in ORM_MANAGERS:
        return None
    if not isinstance(manager_node.value, ast.Name):
        return None
    return manager_node.value.id, manager_node.attr, node.func.attr


def find_unscoped_uuid_lookups(source_root: Path) -> list[UnsafeLookup]:
    """Find direct UUID ORM lookups that omit explicit tenant qualification."""

    findings: list[UnsafeLookup] = []
    for path in sorted(source_root.rglob("*.py")):
        if any(part in {"migrations", "tests", "__pycache__"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            manager_call = _manager_call(node)
            if manager_call is None:
                continue
            model, manager, method = manager_call
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            if not keyword_names.intersection(UUID_LOOKUP_KEYS):
                continue
            if keyword_names.intersection(TENANT_SCOPE_KEYS) or model in EXPLICIT_GLOBAL_MODELS:
                continue
            relative_path = str(path.relative_to(source_root))
            previous_line = source_lines[node.lineno - 2].strip() if node.lineno > 1 else ""
            if previous_line in REVIEWED_SITE_MARKERS:
                permitted_module = REVIEWED_SITE_MARKERS[previous_line]
                if permitted_module is None or relative_path == permitted_module:
                    continue
            findings.append(
                UnsafeLookup(
                    path=str(path.relative_to(source_root)),
                    line=node.lineno,
                    model=model,
                    manager=manager,
                    method=method,
                )
            )
    return findings
