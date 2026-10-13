import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryLocation
from apps.inventory.recalls.models import RegulatoryAlert, RegulatoryTenantImpact
from apps.inventory.services import StockTransferService

pytestmark = pytest.mark.django_db


def grant(tenant, user, capabilities, code):
    role = Role.all_objects.create(tenant=tenant, code=code, name=code, capabilities=capabilities)
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)


@pytest.mark.parametrize("path", ["locations", "batches", "ledger", "balances", "reservations", "transfers", "stocktakes"])
def test_no_capability_account_cannot_read_inventory_sources(tenant_a, path):
    user = User.objects.create_user(username="no-inventory-cap", tenant=tenant_a)
    client = APIClient()
    client.force_login(user)
    response = client.get(f"/api/inventory/{path}/")
    assert response.status_code == 403, response.content


@pytest.mark.parametrize("capability", ["inventory.read", "inventory.manage"])
def test_inventory_reader_and_manager_can_read_sources(tenant_a, capability):
    user = User.objects.create_user(username="inventory-cap", tenant=tenant_a)
    grant(tenant_a, user, [capability], "INV")
    client = APIClient()
    client.force_login(user)
    assert client.get("/api/inventory/locations/").status_code == 200


def test_read_capability_does_not_allow_stock_mutations(tenant_a, branch, inventory_location, sku):
    user = User.objects.create_user(username="inventory-reader", tenant=tenant_a)
    grant(tenant_a, user, ["inventory.read"], "READ_ONLY")
    client = APIClient()
    client.force_login(user)
    for path in ["/api/inventory/transfers/", "/api/inventory/locations/provision/", "/api/inventory/stocktakes/"]:
        assert client.post(path, {}, format="json").status_code == 403
    destination = InventoryLocation.all_objects.create(tenant=tenant_a, branch=branch, location_code="DEST", name="Destination")
    with pytest.raises(ValidationError, match="authority"):
        StockTransferService.request_transfer(tenant=tenant_a, transfer_number="DENIED", source_branch=branch, dest_branch=branch, source_location=inventory_location,
                                             dest_location=destination, requested_by=user, lines_data=[{"sku": sku, "quantity": 1}])


def test_action_specific_transfer_authority_does_not_grant_other_mutations(tenant_a, branch, inventory_location, sku):
    requester = User.objects.create_user(username="narrow-transfer-requester", tenant=tenant_a)
    reviewer = User.objects.create_user(username="narrow-transfer-reviewer", tenant=tenant_a)
    grant(tenant_a, requester, ["inventory.read", "inventory.transfer.request"], "REQUEST")
    grant(tenant_a, reviewer, ["inventory.read", "inventory.transfer.approve"], "APPROVE")
    destination = InventoryLocation.all_objects.create(tenant=tenant_a, branch=branch, location_code="DEST", name="Destination")
    transfer = StockTransferService.request_transfer(tenant=tenant_a, transfer_number="NARROW", source_branch=branch, dest_branch=branch, source_location=inventory_location,
                                                    dest_location=destination, requested_by=requester, lines_data=[{"sku": sku, "quantity": 1}])
    StockTransferService.approve_transfer(transfer=transfer, approver=reviewer)
    with pytest.raises(ValidationError, match="authority"):
        StockTransferService.allocate_and_dispatch(transfer=transfer, dispatcher=reviewer)
    client = APIClient()
    client.force_login(reviewer)
    assert client.post(f"/api/inventory/transfers/{transfer.pk}/dispatch/", {}, format="json").status_code == 403


def test_platform_recall_read_and_delete_require_owner_and_cannot_destroy_evidence(tenant_a):
    user = User.objects.create_user(username="tenant-recall-manager", tenant=tenant_a)
    grant(tenant_a, user, ["recalls.manage"], "RECALLS")
    alert = RegulatoryAlert.objects.create(alert_reference="ACCESS-ALERT", title="Local alert", severity="HIGH")
    client = APIClient()
    client.force_login(user)
    assert client.get("/api/nif/platform/recalls/").status_code == 403
    assert client.delete(f"/api/nif/platform/recalls/{alert.pk}/").status_code == 403
    owner = User.objects.create_user(username="recall-platform-owner", is_platform_admin=True)
    client.force_login(owner)
    assert client.delete(f"/api/nif/platform/recalls/{alert.pk}/").status_code == 405
    assert RegulatoryAlert.objects.filter(pk=alert.pk).exists()


def test_tenant_recall_impact_reads_and_mutations_are_capability_gated(tenant_a):
    user = User.objects.create_user(username="tenant-recall-reader", tenant=tenant_a)
    alert = RegulatoryAlert.objects.create(alert_reference="TENANT-ACCESS-ALERT", title="Local alert", severity="HIGH")
    impact = RegulatoryTenantImpact.all_objects.create(tenant=tenant_a, alert=alert)
    client = APIClient()
    client.force_login(user)
    path = f"/api/nif/recalls/impacts/{impact.pk}/"
    assert client.get(path).status_code == 403
    grant(tenant_a, user, ["inventory.read"], "RECALL_READ")
    assert client.get(path).status_code == 200
    assert client.post(path + "actions/", {}, format="json").status_code == 403
