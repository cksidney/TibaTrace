"""Guard against the tenant-strict manager being used where it returns nothing.

`StrictTenantManager` filters on thread-local tenant context. Outside a request
that sets it -- an API view, a management command, a serialiser method, a
related-manager traversal -- it returns an empty queryset and raises nothing.

The symptom is always a wrong answer rather than a crash, and it was found four
separate times in one day:

* `apps/procurement/api/views.py` returned an empty list for every collection
  and 404'd every detail route, for data that plainly existed.
* `ShiftReportSerializer.has_final_report` reported False for a session with a
  finalised Z, so a closed till read as open on the list somebody consults to
  find tills nobody closed.
* The unclosed-sessions endpoint had the same fault.
* `seed_demo_tenant` missed existing rows on a second run and collided with a
  unique constraint, making an idempotent seed work exactly once.

Each was plausible, silent and took a real test to notice. This scans for the
shape instead of waiting for the fifth.

The rule: inside API view and serialiser code, a tenant-scoped model is queried
through `all_objects` with an explicit tenant filter. `objects` is for code
running inside a request that has already established tenant context.
"""
from __future__ import annotations

import ast
import pathlib

APPS = pathlib.Path(__file__).resolve().parents[1] / "apps"

#: Files where the tenant-strict manager is safe: the tenant context is
#: established by middleware before these run, or the module is not query code.
EXEMPT_PARTS = {"migrations", "tests", "__pycache__"}

#: Modules where `objects` is used deliberately and correctly. Each entry is a
#: decision, not a suppression: adding to this list means somebody has checked
#: that tenant context is set on every path reaching it.
REVIEWED = {
    # Middleware sets tenant context before these run.
    "apps/core/middleware.py",
}


def api_modules() -> list[pathlib.Path]:
    """Every module that serves or serialises an API response."""
    found: list[pathlib.Path] = []
    for path in APPS.rglob("*.py"):
        if any(part in EXEMPT_PARTS for part in path.parts):
            continue
        name = path.name
        if name in {"views.py", "serializers.py"} or "api" in path.parts:
            found.append(path)
    return found


def tenant_scoped_model_names() -> set[str]:
    """Models that actually have a tenant-strict default manager.

    Derived from the app registry rather than hardcoded: a model is tenant
    scoped exactly when it declares `all_objects` alongside `objects`. User and
    Tenant do not, so `User.objects` is a plain manager and flagging it would be
    a false positive -- and a guard that cries wolf is one people learn to
    ignore, which is worse than no guard.
    """
    from django.apps import apps as django_apps

    return {
        model.__name__
        for model in django_apps.get_models()
        if hasattr(model, "all_objects")
    }


def strict_manager_uses(path: pathlib.Path, scoped: set[str] | None = None) -> list[tuple[int, str]]:
    """Uses of the strict default manager on a tenant-scoped model.

    An AST walk rather than a grep, so a mention inside a string or a comment --
    including this module's own docstring -- is not reported as a use.
    """
    scoped = scoped if scoped is not None else tenant_scoped_model_names()
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []

    uses: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "objects"):
            continue
        expression = ast.unparse(node)
        receiver = expression.rsplit(".objects", 1)[0]

        # `self.model.objects` cannot be resolved statically to a model, and it
        # is exactly the shape that emptied the procurement API, so it counts.
        if receiver.endswith("self.model") or receiver == "self.model":
            uses.append((node.lineno, expression))
            continue

        # Otherwise only flag a name that is a tenant-scoped model.
        if receiver.split(".")[-1] in scoped:
            uses.append((node.lineno, expression))
    return uses


#: How many uses exist today, per app. A ratchet rather than a clean assertion:
#: twenty-two were present when this guard was written, spread across code that
#: is actively being changed by other work, and blocking the suite on all of
#: them would have meant either a red suite or no guard at all.
#:
#: The number may go down and must never go up. Fix some, lower the number.
#: Adding one fails immediately, which is the point -- the four found by hand
#: each cost a debugging session, and the fifth should cost a test run.
KNOWN_USES = {
    "inventory": 5,
}


def offenders_by_app() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    scoped = tenant_scoped_model_names()
    for path in api_modules():
        relative = str(path.relative_to(APPS.parent))
        if relative in REVIEWED:
            continue
        app = path.relative_to(APPS).parts[0]
        for line, expression in strict_manager_uses(path, scoped):
            found.setdefault(app, []).append(f"{relative}:{line}  {expression}")
    return found


class TestApiCodeDoesNotUseTheStrictManager:
    def test_no_app_gains_a_new_use(self):
        """The ratchet.

        A new use is a new silent-empty-result bug waiting to be found by
        somebody wondering why a list is empty for data they can see in the
        database.
        """
        found = offenders_by_app()
        grown = {
            app: (len(uses), KNOWN_USES.get(app, 0))
            for app, uses in found.items()
            if len(uses) > KNOWN_USES.get(app, 0)
        }

        assert not grown, (
            "API code has gained a use of the tenant-strict default manager. "
            "Outside a request that has set tenant context it returns nothing "
            "and raises nothing, so the symptom is a wrong answer rather than "
            "an error. Use all_objects with an explicit tenant filter.\n\n"
            + "\n".join(
                f"{app}: {actual} now, {allowed} allowed\n  "
                + "\n  ".join(sorted(found[app]))
                for app, (actual, allowed) in sorted(grown.items())
            )
        )

    def test_the_guarded_apps_stay_clean(self):
        """The apps already fixed must not regress.

        Each of these apps was corrected deliberately; a use reappearing in one
        of them is a straight regression rather than pre-existing debt.

        `medicines` was the largest: fifteen class-attribute querysets, frozen
        empty at import, with no `get_queryset` anywhere in the file.
        """
        found = offenders_by_app()
        for app in (
            "procurement", "insurance", "pricing", "pos_shift", "identity",
            "sales", "customers", "medicines",
        ):
            assert app not in found, (
                f"{app} has regained a tenant-strict manager use in API code:\n  "
                + "\n  ".join(sorted(found[app]))
            )

    def test_the_baseline_is_not_quietly_inflated(self):
        """Nobody raises the allowance instead of fixing the code.

        If the recorded number exceeds what is actually there, somebody has
        padded it -- so this fails and asks them to lower it.
        """
        found = offenders_by_app()
        padded = {
            app: (len(found.get(app, [])), allowed)
            for app, allowed in KNOWN_USES.items()
            if len(found.get(app, [])) < allowed
        }
        assert not padded, (
            "The recorded allowance is higher than the number of uses that "
            "exist. Lower it to lock in the improvement.\n"
            + "\n".join(f"{app}: {actual} actual, {allowed} recorded"
                         for app, (actual, allowed) in sorted(padded.items()))
        )


class TestTheGuardItselfWorks:
    """A scanner that finds nothing because it looks in the wrong place passes
    exactly as loudly as one that works."""

    def test_it_finds_a_planted_use(self, tmp_path):
        planted = tmp_path / "views.py"
        planted.write_text("from x import Claim\n\ndef f():\n    return Claim.objects.all()\n")
        assert strict_manager_uses(planted, {"Claim"}) == [(4, "Claim.objects")]

    def test_it_ignores_a_model_that_is_not_tenant_scoped(self, tmp_path):
        # User and Tenant have plain managers. Flagging them would send somebody
        # looking for an all_objects that does not exist.
        planted = tmp_path / "views.py"
        planted.write_text("from x import User\n\ndef f():\n    return User.objects.all()\n")
        assert strict_manager_uses(planted, {"Claim"}) == []

    def test_it_ignores_all_objects(self, tmp_path):
        planted = tmp_path / "views.py"
        planted.write_text("from x import Claim\n\ndef f():\n    return Claim.all_objects.all()\n")
        assert strict_manager_uses(planted, {"Claim"}) == []

    def test_it_ignores_the_word_in_a_string(self, tmp_path):
        # A grep would report this; the point of the AST walk is that it does
        # not.
        planted = tmp_path / "views.py"
        planted.write_text('MESSAGE = "use Model.objects carefully"\n')
        assert strict_manager_uses(planted, {"Model"}) == []

    def test_it_scans_a_non_empty_set_of_modules(self):
        # If the discovery glob broke, every assertion above would still pass.
        assert len(api_modules()) > 5
