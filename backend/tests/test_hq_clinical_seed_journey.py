"""The seeded clinical workspace must be walkable, not merely populated.

A prescription that exists but cannot be validated, reviewed or verified with
the seeded pharmacist role is a dead end: the cockpit shows the action, the
operator presses it, and the API answers 403. This walks the journey with the
role the seed grants, so a capability renamed on the view set fails here rather
than in front of somebody at a counter.
"""
import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.identity.models import Role, User, UserRole
from apps.prescription.models import Prescription, PrescriptionItem
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def seeded_pharmacist(tenant):
    user = User.objects.get(username=f"hq-demo-pharmacist-{tenant.slug}"[:150])
    role = Role.all_objects.get(tenant=tenant, code="HQ_DEMO_PHARMACIST")
    assert UserRole.all_objects.filter(
        tenant=tenant,
        user=user,
        role=role,
        is_active=True,
    ).exists()
    return user


def test_seeded_pharmacist_can_walk_the_prescription_workflow():
    tenant = Tenant.objects.create(
        name="HQ Clinical Journey Tenant",
        slug="hq-clinical-journey",
        status=Tenant.STATUS_ACTIVE,
    )
    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0, allow_demo_seed=True)

    intake = Prescription.all_objects.get(
        tenant=tenant,
        prescription_number="HQ-DEMO-RX-INTAKE",
    )
    assert intake.status == "RECEIVED"
    # Related managers are tenant-strict; assert through all_objects so the
    # check does not depend on a thread-local tenant being set in the test.
    assert PrescriptionItem.all_objects.filter(prescription=intake).count() == 1

    ready = Prescription.all_objects.get(
        tenant=tenant,
        prescription_number="HQ-DEMO-RX-OPEN",
    )
    assert ready.pharmacist_verification_state == "VERIFIED"
    assert PrescriptionItem.all_objects.filter(prescription=ready).count() == 1

    client = APIClient()
    client.force_authenticate(user=seeded_pharmacist(tenant))
    headers = {"HTTP_X_TENANT_ID": str(tenant.pk)}

    listing = client.get("/api/prescriptions/", **headers)
    assert listing.status_code == 200

    validated = client.post(
        f"/api/prescriptions/{intake.pk}/validate/",
        {},
        format="json",
        **headers,
    )
    assert validated.status_code == 200, validated.content
    intake.refresh_from_db()
    assert intake.legal_validation_state in {"PASSED", "MANUAL_REVIEW", "FAILED"}

    findings = client.get(f"/api/prescriptions/{intake.pk}/findings/", **headers)
    assert findings.status_code == 200

    review = client.post(
        f"/api/prescriptions/{intake.pk}/clinical-review/",
        {"run_cds": False},
        format="json",
        **headers,
    )
    # Started or refused on clinical grounds -- never an authorisation failure.
    assert review.status_code in {200, 201, 400, 409}, review.content
    assert review.status_code != 403


def test_seeded_open_prescription_counts_toward_the_overview_signal():
    tenant = Tenant.objects.create(
        name="HQ Clinical Signal Tenant",
        slug="hq-clinical-signal",
        status=Tenant.STATUS_ACTIVE,
    )
    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0, allow_demo_seed=True)

    final_statuses = {
        "CANCELLED",
        "CLOSED",
        "COMPLETED",
        "EXPIRED",
        "REJECTED",
        "SUPPLIED",
    }
    open_prescriptions = (
        Prescription.all_objects.filter(tenant=tenant)
        .exclude(status__in=final_statuses)
        .count()
    )
    assert open_prescriptions >= 2
