"""Dispensing event replay must be scoped to a tenant, and say so when it is not.

`get_event_stream` read through `AuditEvent.objects` -- the tenant-strict
manager. It filters on thread-local context that nothing sets outside a
request, so a replay from a command, a task or a test read **zero events** and
the projection concluded the aggregate had no history.

For event sourcing that is the worst shape of failure. A rebuild from an empty
stream does not raise; it produces a clean-looking initial state. The aggregate
appears new rather than unreadable, and nothing downstream can tell the
difference.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.identity.models import User
from apps.prescription.models import DispensingEpisode
from apps.prescription.services.dispensing_event_sourcing import (
    DispensingEventSourcingService as Events,
)
from apps.tenancy.models import Tenant


def _episode_for(slug):
    """The smallest real DispensingEpisode: it has six required relations."""
    from apps.inventory.models import InventoryLocation
    from apps.organizations.services import (
        OrganizationProvisioningService,
        SiteProvisioningService,
    )
    from apps.patients.models import Patient
    from apps.practitioners.services import PractitionerRegistrationService
    from apps.prescription.models import Prescription

    tenant = Tenant.objects.create(name=f"Chemists {slug}", slug=slug)
    actor = User.objects.create(username=f"{slug}.actor", tenant=tenant)
    org = OrganizationProvisioningService.provision_organization(
        tenant=tenant, code=f"{slug}-ORG", name=f"{slug} Ltd"
    )
    branch = SiteProvisioningService.provision_site(
        tenant=tenant, organization=org, code=f"{slug}-BR", name=f"{slug} Branch"
    )
    location = InventoryLocation.all_objects.create(
        tenant=tenant, branch=branch, location_code=f"{slug}-LOC", name="Dispensary",
        location_type=InventoryLocation.LocationType.DISPENSARY,
    )
    patient = Patient.all_objects.create(
        tenant=tenant, internal_reference_id=f"{slug}-PAT", patient_number=f"NCD-{slug}",
    )
    practitioner = PractitionerRegistrationService.register_practitioner(
        tenant=tenant, first_name="Test", last_name="Prescriber", profession="DOCTOR",
        registration_number=f"{slug}-REG",
    )
    prescription = Prescription.all_objects.create(
        tenant=tenant, patient=patient, practitioner=practitioner,
        organization=org, location=branch, prescription_number=f"{slug}-RX-1",
    )
    episode = DispensingEpisode.all_objects.create(
        tenant=tenant, dispensing_number=f"{slug.upper()}-DISP-001",
        prescription=prescription, patient=patient, branch=branch,
        pharmacy_location=location, pharmacist=actor,
        idempotency_key=f"{slug}-IDEM-1",
    )
    return {"tenant": tenant, "actor": actor, "episode": episode}


@pytest.fixture
def two_tenants(db):
    return {slug: _episode_for(slug) for slug in ("evt-a", "evt-b")}


def _emit(entry, *events):
    for event_type in events:
        Events.record_event(
            episode=entry["episode"], event_type=event_type, actor=entry["actor"],
        )


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


def test_same_tenant_replay_returns_the_events(two_tenants):
    a = two_tenants["evt-a"]
    _emit(a, "PRESCRIPTION_RECEIVED", "LEGAL_VALIDATED", "CLINICAL_SCREENED")

    stream = Events.get_event_stream(
        tenant_id=a["tenant"].id, episode_id=a["episode"].id
    )
    assert len(stream) == 3, "the replay read no events -- the original defect"
    assert [e["action"] for e in stream] == [
        "PRESCRIPTION_RECEIVED", "LEGAL_VALIDATED", "CLINICAL_SCREENED",
    ]


def test_the_strict_manager_would_have_read_nothing(two_tenants):
    """Why all_objects is required, not merely preferred.

    Outside a request nothing sets tenant context, so the strict manager sees
    no events -- including the tenant's own.
    """
    a = two_tenants["evt-a"]
    _emit(a, "PRESCRIPTION_RECEIVED")

    assert AuditEvent.all_objects.filter(
        tenant_id=a["tenant"].id, object_id=str(a["episode"].id)
    ).exists()
    assert not AuditEvent.objects.filter(
        tenant_id=a["tenant"].id, object_id=str(a["episode"].id)
    ).exists()


# ---------------------------------------------------------------------------
# Cross-tenant refusal must be explicit, not invisibility
# ---------------------------------------------------------------------------


def test_tenant_a_cannot_replay_tenant_b_events(two_tenants):
    """Refused by name, not by returning an empty list.

    A WHERE clause that filters out another tenant's aggregate yields an empty
    stream, and an empty stream is a legitimate state. The caller could not
    tell a foreign aggregate from a brand-new one.
    """
    a, b = two_tenants["evt-a"], two_tenants["evt-b"]
    _emit(b, "PRESCRIPTION_RECEIVED", "LEGAL_VALIDATED")

    with pytest.raises(ValidationError, match="not owned by tenant"):
        Events.get_event_stream(tenant_id=a["tenant"].id, episode_id=b["episode"].id)

    with pytest.raises(ValidationError, match="not owned by tenant"):
        Events.replay_projection(tenant_id=a["tenant"].id, episode_id=b["episode"].id)

    # And the refusal does not disclose that the id exists elsewhere: replay
    # must not become an oracle for another tenant's aggregate ids.
    with pytest.raises(ValidationError) as foreign:
        Events.get_event_stream(tenant_id=a["tenant"].id, episode_id=b["episode"].id)
    import uuid as _uuid
    with pytest.raises(ValidationError) as absent:
        Events.get_event_stream(tenant_id=a["tenant"].id, episode_id=_uuid.uuid4())
    assert type(foreign.value) is type(absent.value)


def test_missing_tenant_context_raises_rather_than_returning_empty(two_tenants):
    a = two_tenants["evt-a"]
    _emit(a, "PRESCRIPTION_RECEIVED")

    for absent in (None, ""):
        with pytest.raises(ValidationError, match="requires an explicit tenant"):
            Events.get_event_stream(tenant_id=absent, episode_id=a["episode"].id)


def test_an_unknown_aggregate_is_refused(two_tenants):
    import uuid

    a = two_tenants["evt-a"]
    with pytest.raises(ValidationError, match="not owned by tenant"):
        Events.get_event_stream(tenant_id=a["tenant"].id, episode_id=uuid.uuid4())


def test_an_empty_stream_is_distinguishable_from_an_inaccessible_one(two_tenants):
    """The distinction the defect destroyed.

    A real episode with no events replays cleanly and reports zero. A foreign
    or absent one raises. Both used to return an empty list.
    """
    a, b = two_tenants["evt-a"], two_tenants["evt-b"]

    empty = Events.replay_projection(
        tenant_id=a["tenant"].id, episode_id=a["episode"].id
    )
    assert empty["event_count"] == 0
    assert empty["replayed_lifecycle_state"] == "REQUEST_PLANNED"

    with pytest.raises(ValidationError):
        Events.replay_projection(tenant_id=a["tenant"].id, episode_id=b["episode"].id)


# ---------------------------------------------------------------------------
# Stream invariants
# ---------------------------------------------------------------------------


def test_replay_order_is_deterministic(two_tenants):
    """Ordered by (created_at, id).

    created_at alone ties when events are written inside one transaction, and a
    tie makes replay order depend on however the database returned the rows.
    """
    a = two_tenants["evt-a"]
    actions = [f"LIFECYCLE_TRANSITION_STATE_{i}" for i in range(8)]
    _emit(a, *actions)

    runs = [
        [e["action"] for e in Events.get_event_stream(
            tenant_id=a["tenant"].id, episode_id=a["episode"].id
        )]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert runs[0] == actions


def test_events_are_never_mixed_between_tenants(two_tenants):
    a, b = two_tenants["evt-a"], two_tenants["evt-b"]
    _emit(a, "PRESCRIPTION_RECEIVED", "LEGAL_VALIDATED")
    _emit(b, "PRESCRIPTION_RECEIVED")

    stream_a = Events.get_event_stream(
        tenant_id=a["tenant"].id, episode_id=a["episode"].id
    )
    assert len(stream_a) == 2
    ids = {e["audit_id"] for e in stream_a}
    foreign = set(
        str(pk) for pk in AuditEvent.all_objects.filter(
            tenant_id=b["tenant"].id
        ).values_list("pk", flat=True)
    )
    assert not (ids & foreign)


def test_an_event_cannot_be_appended_without_a_tenant(two_tenants):
    """Every event is tenant-bound at append time."""
    a = two_tenants["evt-a"]
    orphan = DispensingEpisode(dispensing_number="ORPHAN-1")  # unsaved, no tenant

    with pytest.raises(ValidationError, match="no tenant"):
        Events.record_event(
            episode=orphan, event_type="PRESCRIPTION_RECEIVED", actor=a["actor"],
        )


def test_recorded_events_are_immutable_and_undeletable(two_tenants):
    a = two_tenants["evt-a"]
    _emit(a, "PRESCRIPTION_RECEIVED")
    event = AuditEvent.all_objects.filter(tenant_id=a["tenant"].id).first()

    event.action = "TAMPERED"
    with pytest.raises(ValidationError, match="immutable"):
        event.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        event.delete()


def test_replay_reconstructs_state_from_the_stream(two_tenants):
    a = two_tenants["evt-a"]
    _emit(
        a, "PRESCRIPTION_RECEIVED", "LEGAL_VALIDATED", "CLINICAL_SCREENED",
        "PHARMACIST_REVIEWED", "INVENTORY_RESERVED", "PAYMENT_COMPLETED",
    )
    projection = Events.replay_projection(
        tenant_id=a["tenant"].id, episode_id=a["episode"].id
    )
    assert projection["event_count"] == 6
    assert projection["replayed_inventory_state"] == "RESERVED"
    assert projection["replayed_payment_state"] == "PAID"
    assert len(projection["timeline"]) == 6


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------


def test_the_lookup_audit_reports_nothing_for_the_event_sourcing_module():
    import pathlib

    from apps.prescription.management.lookup_safety import find_unscoped_uuid_lookups

    apps_root = pathlib.Path(__file__).resolve().parents[1] / "apps"
    findings = [
        f for f in find_unscoped_uuid_lookups(apps_root)
        if "dispensing_event_sourcing" in f.path
    ]
    assert findings == [], findings


def test_no_suppression_marker_was_introduced():
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "apps" / "prescription" / "services" / "dispensing_event_sourcing.py"
    ).read_text()
    for marker in ("# tenant-safety:", "# noqa", "# nosec", "# type: ignore"):
        assert marker not in source, f"suppression introduced: {marker}"
