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

from collections import defaultdict
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
    ("insurance_claims", "insurance", "PrescriptionClaim", False),
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
    owned_ids_by_model: dict[str, set[str]] = defaultdict(set)
    for entry in DemoScenarioObject.all_objects.filter(tenant=tenant).select_related("content_type"):
        key = (entry.content_type.app_label, entry.content_type.model)
        owned_by_ct[key] = owned_by_ct.get(key, 0) + 1
        owned_ids_by_model[entry.content_type.model].add(str(entry.object_id))

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
        if label == "audit_events":
            # Audit events are immutable and emitted by domain services.  Prove
            # their narrow seed provenance from the exact owned target instead.
            registry_ids = owned_ids_by_model.get("auditevent", set())
            dc.demo_owned = len(
                registry_ids | _proven_demo_audit_event_ids(tenant, owned_ids_by_model)
            )
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
        Role.all_objects.filter(tenant=tenant, code="TENANT_ADMIN").only(
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
        and not UserRole.all_objects.filter(tenant=tenant, role=role).exists()
    )


def _is_canonical_demo_designation_audit(event, tenant) -> bool:
    """Recognise only the audited act which designates this exact demo tenant.

    Designation is a required, immutable governance action performed before
    seeding.  Its one audit event is therefore infrastructure rather than
    tenant business activity.  The event is deliberately matched in full so a
    normal audit record can never be used to make an in-use tenant seedable.
    """
    metadata = event.metadata or {}
    return (
        tenant.is_demo
        and event.action == "DEMO_TENANT_DESIGNATED"
        and event.outcome == "SUCCESS"
        and event.actor_id is not None
        and event.model_name == ""
        and event.object_id == ""
        and metadata.get("tenant_id") == str(tenant.id)
        and metadata.get("tenant_slug") == tenant.slug
        and metadata.get("tenant_name") == tenant.name
        and metadata.get("is_demo_before") is False
        and metadata.get("is_demo_after") is True
    )


_DEMO_AUDIT_ACTION_TARGETS = {
    "PATIENT_CREATED": "patient",
    "PRACTITIONER_CONTROLLED_AUTHORITY_GRANTED": "practitioner",
    "SUPPLIER_QUALIFICATION_REGISTERED": "supplierqualification",
    "SUPPLIER_QUALIFICATION_VERIFIED": "supplierqualification",
    "INSURANCE_COVERAGE_CREATED": "insurancecoverage",
    "INSURANCE_BENEFIT_DEFINED": "coveragebenefit",
}
_SYSTEM_GENERATED_DEMO_AUDIT_ACTIONS = {
    "INSURANCE_COVERAGE_CREATED",
    "INSURANCE_BENEFIT_DEFINED",
}


def _proven_demo_audit_event_ids(tenant, owned_ids_by_model: dict[str, set[str]]) -> set[str]:
    """Return immutable audit rows whose exact target proves seed provenance.

    A domain service writes its audit evidence after it creates the target, so
    the orchestrator cannot claim it as a normal generated object.  Duplicated
    or unrelated audit facts deliberately remain unproven and block seeding.
    """
    from apps.audit.models import AuditEvent

    events = list(
        AuditEvent.all_objects.filter(tenant=tenant).only(
            "id", "action", "actor_id", "model_name", "object_id", "outcome", "metadata"
        )
    )
    proven: set[str] = set()

    designation_events = [
        event for event in events if _is_canonical_demo_designation_audit(event, tenant)
    ]
    if len(designation_events) == 1:
        proven.add(str(designation_events[0].id))

    demo_user_ids = owned_ids_by_model.get("user", set())
    candidates: dict[tuple[str, str, str], list] = defaultdict(list)
    for event in events:
        expected_model = _DEMO_AUDIT_ACTION_TARGETS.get(event.action)
        actual_model = event.model_name.lower()
        if (
            expected_model is None
            or actual_model != expected_model
            or event.outcome != "SUCCESS"
            or str(event.object_id) not in owned_ids_by_model.get(expected_model, set())
        ):
            continue
        if event.actor_id is None:
            if event.action not in _SYSTEM_GENERATED_DEMO_AUDIT_ACTIONS:
                continue
        elif str(event.actor_id) not in demo_user_ids:
            continue
        candidates[(event.action, actual_model, str(event.object_id))].append(event)

    for matching_events in candidates.values():
        if len(matching_events) == 1:
            proven.add(str(matching_events[0].id))
    return proven


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
    demo_owned = sum(v.demo_owned for v in live.values())

    if total == 0:
        return EMPTY_SAFE_TO_SEED

    # The canonical provisioning role is expected on a provisioned demo
    # tenant, even after generated roles exist. Nothing else may use this
    # exemption: normal/custom roles, assigned roles and every clinical,
    # commercial or transactional record remain unclassified and block a seed.
    bootstrap_domains = set()
    if live.get("roles") is not None and _is_unassigned_bootstrap_tenant_admin(tenant):
        bootstrap_domains.add("roles")
    from apps.audit.models import AuditEvent

    audit_rows = list(AuditEvent.all_objects.filter(tenant=tenant))
    designation_only = len(audit_rows) == 1 and _is_canonical_demo_designation_audit(audit_rows[0], tenant)
    if designation_only:
        bootstrap_domains.add("audit_events")
    unaccounted = sum(
        value.unaccounted
        for key, value in live.items()
        if key not in bootstrap_domains
    )

    only_bootstrap = (
        demo_owned == (1 if designation_only else 0)
        and bool(bootstrap_domains)
        and unaccounted == 0
    )
    if only_bootstrap:
        report.notes.append(
            "only canonical bootstrap provisioning records are present; "
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
