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
            previous_line = source_lines[node.lineno - 2].strip() if node.lineno > 1 else ""
            if previous_line == "# tenant-safety: immutable-existence-check":
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
