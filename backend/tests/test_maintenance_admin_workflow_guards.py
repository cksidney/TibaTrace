"""Every registered maintenance model and custom admin route is inspection-only."""
from django.contrib import admin
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.admin_site import WorkflowAdminSite
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.identity.models import User
from apps.sales.models import PriceList
from apps.tenancy.models import Tenant


def test_all_registered_models_deny_mutations_even_to_superusers():
    request = RequestFactory().get("/admin/")
    request.user = User(username="in-memory-admin", is_superuser=True, is_staff=True)
    assert isinstance(admin.site._wrapped, WorkflowAdminSite)
    assert admin.site._registry
    for model_admin in admin.site._registry.values():
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
        assert not model_admin.get_actions(request)


def test_custom_maintenance_routes_cannot_write():
    import pytest
    from django.core.exceptions import PermissionDenied

    called = []
    guarded = admin.site.admin_view(lambda request: called.append(True) or HttpResponse("unsafe write"))
    request = RequestFactory().post("/admin/custom-command/", {"status": "ACTIVE"})
    request.user = User(username="in-memory-admin", is_superuser=True, is_staff=True)
    with pytest.raises(PermissionDenied, match="read-only"):
        guarded(request)
    assert called == []


def test_ordinary_tenant_staff_cannot_use_maintenance_inspector():
    request = RequestFactory().get("/admin/")
    request.user = User(username="tenant-staff", is_staff=True)
    assert not admin.site.has_permission(request)


def test_admin_price_edits_and_unscoped_reads_are_blocked(client, db):
    tenant = Tenant.objects.create(name="Maintenance scope", slug="maintenance-scope")
    owner = User.objects.create_user(username="maintenance-owner", is_superuser=True, is_staff=True)
    row = PriceList.all_objects.create(tenant=tenant, code="P", name="Published", status="ACTIVE", effective_from="2026-01-01")
    client.force_login(owner)
    response = client.post(f"/admin/sales/pricelist/{row.pk}/change/", {"name": "Bypassed", "status": "DRAFT"})
    assert response.status_code == 403
    row.refresh_from_db()
    assert row.name == "Published" and row.status == "ACTIVE"
    inspection = client.get(f"/admin/sales/pricelist/{row.pk}/change/", HTTP_X_TENANT_ID=str(tenant.pk))
    assert inspection.status_code == 200 and "Published" in inspection.content.decode()
    assert b'name="_save"' not in inspection.content
    request = RequestFactory().get("/admin/sales/pricelist/")
    request.user = owner
    model_admin = admin.site._registry[PriceList]
    token = set_current_tenant_id(None)
    try:
        assert not model_admin.get_queryset(request).exists()
        set_current_tenant_id(str(tenant.pk))
        assert list(model_admin.get_queryset(request).values_list("pk", flat=True)) == [row.pk]
    finally:
        reset_current_tenant_id(token)


def test_login_and_authenticated_logout_still_work(client, db):
    owner = User.objects.create_user(username="maintenance-login", password="Test-only-pass-984!", is_superuser=True, is_staff=True)
    response = client.post("/admin/login/?next=/admin/", {"username": owner.username, "password": "Test-only-pass-984!", "next": "/admin/"})
    assert response.status_code == 302
    assert client.post("/admin/logout/").status_code == 200
