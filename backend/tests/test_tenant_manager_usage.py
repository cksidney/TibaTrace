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


#: Empty, and it should stay that way.
#:
#: This began as a ratchet because twenty-two uses were present when the guard
#: was written, spread across code other work was actively changing, and failing
#: the suite on all of them would have meant either a red suite or no guard. They
#: have since been fixed app by app -- procurement, insurance, pricing,
#: pos_shift, identity, sales, customers, medicines and finally inventory -- so
#: the allowance is now nil and any use at all fails.
#:
#: Leave it empty. If a use has to be added deliberately, put the module in
#: REVIEWED with a note explaining why tenant context is guaranteed there,
#: rather than re-opening a numeric allowance nobody will ever lower again.
KNOWN_USES: dict[str, int] = {}


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
        `inventory` was the last, and had the same shape across all five of its
        viewsets -- stock levels, batches and the ledger returned nothing to
        every caller.
        """
        found = offenders_by_app()
        for app in (
            "procurement", "insurance", "pricing", "pos_shift", "identity",
            "sales", "customers", "medicines", "inventory",
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


# ---------------------------------------------------------------------------
# Service-layer audit
#
# The API audit above scans views, serializers and api modules. Stage 2B.1
# found two defects it could not see, both in service code:
#
#   * receive_line locked the purchase-order line through the strict manager,
#     so outside a request the lock raised DoesNotExist -- and took the
#     over-receipt guard down with it.
#   * returns_service wrote through the same manager.
#
# Services run from every context: a request, a management command, a Celery
# task, an importer. That makes them the *most* exposed layer, and it was the
# one nothing scanned.
# ---------------------------------------------------------------------------

#: Only read-shaped calls are flagged. `Model.objects.create(...)` inserts a
#: row; the manager's filter does not apply to an insert, so it is inconsistent
#: rather than broken. A read returns an empty queryset and the caller believes
#: the data is not there -- which is the failure that matters.
READ_METHODS = frozenset(
    {
        "filter", "get", "exclude", "exists", "count", "first", "last", "all",
        "aggregate", "values", "values_list", "select_for_update",
        "get_or_create", "update_or_create", "update", "delete",
    }
)

#: Modules that establish tenant context before querying. Every management
#: command in this repository that reads through the strict manager calls
#: set_current_tenant_id first, which makes the use correct -- flagging them
#: would be a guard that cries wolf, and those get ignored.
TENANT_CONTEXT_SETTER = "set_current_tenant_id"


def service_layer_modules() -> list[pathlib.Path]:
    """Every module that runs outside, or independently of, a request."""
    found: list[pathlib.Path] = []
    for path in APPS.rglob("*.py"):
        if any(part in EXEMPT_PARTS for part in path.parts):
            continue
        parts, name = path.parts, path.name
        is_service = (
            "services" in parts
            or name == "services.py"
            or name.endswith(("_service.py", "_services.py"))
            or name in {"provisioning.py", "authoring.py", "onboarding.py"}
        )
        is_worker = "commands" in parts or name in {"tasks.py", "signals.py"}
        is_generator = "generation" in parts
        if is_service or is_worker or is_generator:
            found.append(path)
    return sorted(found)


def unscoped_service_reads(path: pathlib.Path, scoped: set[str] | None = None):
    """Read-shaped strict-manager calls in a module with no tenant context."""
    scoped = scoped if scoped is not None else tenant_scoped_model_names()
    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []
    if TENANT_CONTEXT_SETTER in source:
        return []

    uses: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in READ_METHODS:
            continue
        receiver = node.func.value
        if not (isinstance(receiver, ast.Attribute) and receiver.attr == "objects"):
            continue
        model = ast.unparse(receiver).rsplit(".objects", 1)[0].split(".")[-1]
        if model in scoped:
            uses.append((node.lineno, f"{model}.objects.{node.func.attr}"))
    return uses


def service_offenders() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    scoped = tenant_scoped_model_names()
    for path in service_layer_modules():
        relative = str(path.relative_to(APPS.parent))
        if relative in REVIEWED:
            continue
        for line, expression in unscoped_service_reads(path, scoped):
            found.setdefault(relative, []).append(f"{relative}:{line}  {expression}")
    return found


class TestServiceCodeDoesNotReadThroughTheStrictManager:
    def test_no_unscoped_service_layer_reads(self):
        """Empty, and it should stay that way.

        Three were present when this guard was written -- two in
        medicines.services and one in inventory.recalls.services, all
        get_or_create or update_or_create whose lookup half matched nothing
        without tenant context and then collided with a unique constraint on
        the create. All three are fixed; the list is nil.
        """
        offenders = service_offenders()
        assert offenders == {}, (
            "service-layer code reads through the tenant-strict manager:\n"
            + "\n".join(sorted(line for lines in offenders.values() for line in lines))
        )

    def test_the_audit_covers_more_than_the_api_layer(self):
        """Guards the scope itself: a narrowed glob would silently pass."""
        modules = {str(p.relative_to(APPS.parent)) for p in service_layer_modules()}
        assert any("services" in m for m in modules), "services not scanned"
        assert any("commands" in m for m in modules), "management commands not scanned"
        assert any("generation" in m for m in modules), "demo generators not scanned"
        assert len(modules) > 50, f"only {len(modules)} modules scanned"

    # -- regression fixtures ------------------------------------------------

    def test_it_catches_a_planted_service_read(self, tmp_path):
        planted = tmp_path / "billing_service.py"
        planted.write_text(
            "def charge(invoice_id):\n"
            "    return Invoice.objects.filter(pk=invoice_id).first()\n"
        )
        assert unscoped_service_reads(planted, {"Invoice"})

    def test_it_catches_a_planted_get_or_create(self, tmp_path):
        """The exact shape of the three defects this guard was written for."""
        planted = tmp_path / "services.py"
        planted.write_text(
            "def ensure(tenant, code):\n"
            "    return Widget.objects.get_or_create(tenant=tenant, code=code)\n"
        )
        assert unscoped_service_reads(planted, {"Widget"})

    def test_it_catches_a_planted_select_for_update(self, tmp_path):
        """The receive_line defect: a lock that returns nothing and raises."""
        planted = tmp_path / "receiving_service.py"
        planted.write_text(
            "def lock(pk):\n"
            "    return OrderLine.objects.select_for_update().get(pk=pk)\n"
        )
        assert unscoped_service_reads(planted, {"OrderLine"})

    def test_it_ignores_a_create(self, tmp_path):
        """An insert is unaffected by the manager's filter."""
        planted = tmp_path / "services.py"
        planted.write_text(
            "def make(tenant):\n    return Widget.objects.create(tenant=tenant)\n"
        )
        assert unscoped_service_reads(planted, {"Widget"}) == []

    def test_it_ignores_a_module_that_establishes_tenant_context(self, tmp_path):
        """Every management command here sets context before reading."""
        planted = tmp_path / "check_something.py"
        planted.write_text(
            "from apps.core.tenancy import set_current_tenant_id\n"
            "def run(tenant):\n"
            "    set_current_tenant_id(tenant.id)\n"
            "    return Widget.objects.filter(active=True)\n"
        )
        assert unscoped_service_reads(planted, {"Widget"}) == []

    def test_it_ignores_all_objects(self, tmp_path):
        planted = tmp_path / "services.py"
        planted.write_text(
            "def read(tenant):\n"
            "    return Widget.all_objects.filter(tenant=tenant)\n"
        )
        assert unscoped_service_reads(planted, {"Widget"}) == []

    def test_it_ignores_a_model_without_a_strict_manager(self, tmp_path):
        """User and Tenant carry plain managers; flagging them cries wolf."""
        planted = tmp_path / "services.py"
        planted.write_text("def read():\n    return User.objects.filter(is_active=True)\n")
        assert unscoped_service_reads(planted, {"Widget"}) == []
