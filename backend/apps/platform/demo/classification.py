"""Classify what already exists in a tenant before the engine writes anything.

Low row counts do not mean "safe". A tenant with three prescriptions and one
audit event is a tenant that has been used. This module therefore separates
three questions:

* what exists;
* how much of it the demo engine owns (proved by the ownership registry);
* whether anything is left over that nobody can account for.

Anything unaccounted for produces UNCLASSIFIED_DATA_PRESENT, which blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.apps import apps as django_apps

EMPTY_SAFE_TO_SEED = "EMPTY_SAFE_TO_SEED"
DEMO_DATA_PRESENT = "DEMO_DATA_PRESENT"
REAL_DATA_PRESENT = "REAL_DATA_PRESENT"
UNCLASSIFIED_DATA_PRESENT = "UNCLASSIFIED_DATA_PRESENT"
BLOCKED = "BLOCKED"

#: (label, app_label, model_name, immutable). Immutable domains can never be
#: deleted by a reset -- they are archived in place.
INSPECTED_MODELS: tuple[tuple[str, str, str, bool], ...] = (
    ("users", "identity", "User", False),
    ("roles", "identity", "Role", False),
    ("locations", "organizations", "Location", False),
    ("organizations", "organizations", "Organization", False),
    ("departments", "organizations", "Department", False),
    ("department_memberships", "organizations", "DepartmentMembership", False),
    ("practitioners", "practitioners", "Practitioner", False),
    ("patients", "patients", "Patient", False),
    ("commercial_skus", "medicines", "CommercialSKU", False),
    ("inventory_batches", "inventory", "InventoryBatch", False),
    ("inventory_ledger_entries", "inventory", "InventoryLedgerEntry", True),
    ("prescriptions", "prescription", "Prescription", True),
    ("dispensing_episodes", "prescription", "DispensingEpisode", False),
    ("payment_intents", "prescription", "PaymentIntent", False),
    ("payment_settlements", "prescription", "PaymentSettlement", False),
    ("purchase_orders", "procurement", "PurchaseOrder", False),
    ("insurance_claims", "insurance", "InsuranceClaim", False),
    ("audit_events", "audit", "AuditEvent", True),
    ("pos_registers", "pos_shift", "PosRegister", False),
    ("register_sessions", "pos_shift", "RegisterSession", False),
)


@dataclass
class DomainCount:
    label: str
    total: int = 0
    demo_owned: int = 0
    immutable: bool = False
    available: bool = True

    @property
    def unaccounted(self) -> int:
        return max(0, self.total - self.demo_owned)


@dataclass
class ClassificationReport:
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    is_demo: bool
    domains: dict[str, DomainCount] = field(default_factory=dict)
    demo_runs: int = 0
    verdict: str = BLOCKED
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {k: v.total for k, v in sorted(self.domains.items())}

    def as_dict(self) -> dict:
        return {
            "tenant": {
                "id": self.tenant_id,
                "slug": self.tenant_slug,
                "name": self.tenant_name,
                "is_demo": self.is_demo,
            },
            "demo_scenario_runs": self.demo_runs,
            "domains": {
                k: {
                    "total": v.total,
                    "demo_owned": v.demo_owned,
                    "unaccounted": v.unaccounted,
                    "immutable": v.immutable,
                    "model_available": v.available,
                }
                for k, v in sorted(self.domains.items())
            },
            "verdict": self.verdict,
            "notes": self.notes,
        }


def _tenant_queryset(model, tenant):
    """Tenant-scoped queryset, preferring the unscoped manager where present.

    `all_objects` bypasses the current-tenant context, which a management
    command does not set. Filtering explicitly on the tenant keeps the read
    inside the boundary.
    """
    manager = getattr(model, "all_objects", None) or model._default_manager
    field_names = {f.name for f in model._meta.get_fields() if hasattr(f, "attname")}
    if "tenant" in field_names:
        return manager.filter(tenant=tenant)
    return None


def classify_tenant(tenant) -> ClassificationReport:
    from apps.platform.demo.models import DemoScenarioObject, DemoScenarioRun

    report = ClassificationReport(
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        is_demo=bool(tenant.is_demo),
    )
    report.demo_runs = DemoScenarioRun.all_objects.filter(tenant=tenant).count()

    owned_by_ct: dict[tuple[str, str], int] = {}
    for entry in DemoScenarioObject.all_objects.filter(tenant=tenant).select_related("content_type"):
        key = (entry.content_type.app_label, entry.content_type.model)
        owned_by_ct[key] = owned_by_ct.get(key, 0) + 1

    for label, app_label, model_name, immutable in INSPECTED_MODELS:
        dc = DomainCount(label=label, immutable=immutable)
        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:
            dc.available = False
            report.notes.append(f"{app_label}.{model_name} not present in this build")
            report.domains[label] = dc
            continue

        qs = _tenant_queryset(model, tenant)
        if qs is None:
            dc.available = False
            report.notes.append(f"{label}: model has no tenant field; not tenant-scoped")
            report.domains[label] = dc
            continue

        dc.total = qs.count()
        dc.demo_owned = owned_by_ct.get((app_label, model_name.lower()), 0)
        report.domains[label] = dc

    report.verdict = _verdict(report, tenant)
    return report


def _is_unassigned_bootstrap_tenant_admin(tenant) -> bool:
    """Recognise the sole system role created when a tenant is provisioned.

    ``TENANT_ADMIN`` is infrastructure, not business data.  A freshly
    provisioned tenant can therefore contain that one unassigned system role
    before its first user exists.  Treating it as unexplained data made an
    otherwise empty tenant impossible to seed, while accepting any other role
    would weaken the conservative classification boundary.
    """
    from apps.identity.models import Role, UserRole

    roles = list(
        Role.all_objects.filter(tenant=tenant).only(
            "id", "code", "name", "is_active", "is_system"
        )
    )
    if len(roles) != 1:
        return False

    role = roles[0]
    return (
        role.code == "TENANT_ADMIN"
        and role.name == "Tenant administrator"
        and role.is_system
        and role.is_active
        and not UserRole.all_objects.filter(tenant=tenant).exists()
    )


def _verdict(report: ClassificationReport, tenant) -> str:
    """Decide the verdict conservatively.

    Order matters. Unaccounted rows outrank everything else, because an object
    nobody can attribute is the one case where a reset could destroy real work.
    """
    live = {k: v for k, v in report.domains.items() if v.available}
    if not live:
        report.notes.append("no inspectable models; cannot classify")
        return BLOCKED

    total = sum(v.total for v in live.values())
    unaccounted = sum(v.unaccounted for v in live.values())
    demo_owned = sum(v.demo_owned for v in live.values())

    if total == 0:
        return EMPTY_SAFE_TO_SEED

    # A lone bootstrap user and the canonical, unassigned system role are
    # expected on a provisioned-but-unused tenant.  Nothing else may use this
    # exemption: normal/custom roles, assigned roles and every clinical or
    # transactional record remain unclassified and block a seed.
    bootstrap_domains = set()
    if live.get("users") is not None and live["users"].unaccounted == 1:
        bootstrap_domains.add("users")
    if live.get("roles") is not None and _is_unassigned_bootstrap_tenant_admin(tenant):
        bootstrap_domains.add("roles")

    only_bootstrap = (
        demo_owned == 0
        and bool(bootstrap_domains)
        and all(
            v.unaccounted == 0
            for key, v in live.items()
            if key not in bootstrap_domains
        )
    )
    if only_bootstrap:
        report.notes.append(
            "only canonical bootstrap provisioning records are unaccounted for; "
            "treated as empty for seeding"
        )
        return EMPTY_SAFE_TO_SEED

    if unaccounted > 0:
        transactional = [
            k
            for k in ("prescriptions", "dispensing_episodes", "payment_settlements",
                      "inventory_ledger_entries", "insurance_claims", "purchase_orders")
            if live.get(k) and live[k].unaccounted > 0
        ]
        if transactional:
            report.notes.append(
                "unaccounted transactional records present in: " + ", ".join(transactional)
            )
            return REAL_DATA_PRESENT
        report.notes.append(f"{unaccounted} record(s) not attributable to a demo run")
        return UNCLASSIFIED_DATA_PRESENT

    if demo_owned > 0:
        return DEMO_DATA_PRESENT
    return UNCLASSIFIED_DATA_PRESENT
