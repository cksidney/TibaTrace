"""The HQ workspace aggregate must stay JSON-serialisable for seeded tenants.

The cockpit loads every workbench from one payload. A single field holding a
model instance rather than a value takes the whole response to a 500, and the
operator sees an empty workspace with no indication of which panel broke it --
so this asserts the payload renders, not merely that the view returns.
"""
import pytest
from django.core.management import call_command

from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def test_hq_workspace_payload_renders_for_a_fully_seeded_tenant(client, django_user_model):
    tenant = Tenant.objects.create(
        name="HQ Workspace Contract Tenant",
        slug="hq-workspace-contract",
        status=Tenant.STATUS_ACTIVE,
    )
    call_command("seed_hq_workspaces", tenant_slug=tenant.slug, verbosity=0, allow_demo_seed=True)

    admin = django_user_model.objects.create_user(
        username="hq-workspace-contract-admin",
        password="test-password",
        is_platform_admin=True,
    )
    client.force_login(admin)

    response = client.get("/api/hq/workspace/", HTTP_X_TENANT_ID=str(tenant.pk))

    assert response.status_code == 200
    # Rendering is where a model instance in the payload fails, not the view.
    body = response.json()

    clinical = body["clinical"]
    assert clinical["counts"]["code_systems"] >= 1
    assert clinical["counts"]["value_sets"] >= 1
    for row in clinical["code_systems"] + clinical["value_sets"]:
        assert isinstance(row["version"], str)
        assert row["version"]

    modules = {module["key"] for module in body["business_modules"]}
    assert {"users", "purchase-orders", "prescriptions"} <= modules
