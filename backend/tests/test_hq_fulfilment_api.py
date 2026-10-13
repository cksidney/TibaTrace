# ruff: noqa: F811
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from tests.test_pos_retail_transactions import world  # noqa: F401

from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.customers.models import Customer, CustomerDeliveryAddress
from apps.identity.models import User
from apps.sales.models import PickingTask, PickingWave, SalesOrder
from apps.sales.services import SalesAllocationService, SalesApprovalService, SalesOrderService, SalesReservationService

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def tenant_context(world):
    token = set_current_tenant_id(world["tenant"].pk)
    world["client"].defaults["HTTP_X_TENANT_ID"] = str(world["tenant"].pk)
    yield
    reset_current_tenant_id(token)


def test_operator_can_complete_actual_allocated_stock_to_evidenced_delivery_without_duplicates(world):
    tenant, operator = world["tenant"], world["operator"]
    customer = Customer.all_objects.create(tenant=tenant, customer_number="HQ-SYNTHETIC", legal_name="Synthetic buyer", customer_type="WHOLESALE", status="ACTIVE")
    address = CustomerDeliveryAddress.all_objects.create(tenant=tenant, customer=customer, address_code="MAIN", recipient_name="Synthetic recipient", address_line1="Synthetic address", city="Nairobi")
    order = SalesOrderService.create_sales_order(tenant=tenant, branch=world["branch"], customer=customer, created_by=operator)
    SalesOrderService.add_order_line(sales_order=order, sku=world["sku"], requested_quantity=Decimal("2"), unit="pack", pricing_data={"base_unit_price":Decimal("125"), "agreed_unit_price":Decimal("125"), "discount_amount":Decimal("0"), "discount_percentage":Decimal("0")})
    SalesOrderService.submit_order(sales_order=order)
    SalesApprovalService.approve_order(sales_order=order, approver=operator)
    SalesReservationService.reserve_order(sales_order=order, actor=operator)
    SalesAllocationService.allocate_order(sales_order=order, actor=operator)
    client = world["client"]
    sequence = 0
    def post(resource, identifier, action, values=None, *, key=None, expected=201):
        nonlocal sequence
        sequence += 1
        response = client.post(f"/api/sales/{resource}/{identifier}/{action}/", {"idempotency_key":key or f"HQ-SYNTHETIC-{sequence}", **(values or {})}, format="json")
        assert response.status_code == expected, response.content
        return response.json()
    wave = post("orders", order.pk, "picking-wave", key="HQ-WAVE-RETRY")
    assert post("orders", order.pk, "picking-wave", key="HQ-WAVE-RETRY", expected=200)["id"] == wave["id"]
    assert PickingWave.all_objects.count() == 1
    task = PickingTask.all_objects.get(sales_order=order)
    post("picking-tasks", task.pk, "assign", expected=200)
    post("picking-tasks", task.pk, "start", expected=200)
    post("picking-tasks", task.pk, "record", {"picked_quantity":"2", "short_quantity":"0"}, expected=200)
    post("picking-tasks", task.pk, "verify", expected=400)
    verifier = User.objects.create_user(username="hq-independent-checker", tenant=tenant, is_superuser=True)
    client.force_authenticate(user=verifier)
    post("picking-tasks", task.pk, "verify", expected=200)
    client.force_authenticate(user=operator)
    session = post("orders", order.pk, "packing-session")
    package = post("packing-sessions", session["id"], "create-package", {"temperature_zone":"AMBIENT", "package_type":"Actual test package"})
    packed = post("packages", package["id"], "pack-line", {"picking_task_id":str(task.pk), "quantity":"2"}, key="PACK-RETRY")
    assert len(packed["lines"]) == 1
    assert len(post("packages", package["id"], "pack-line", {"picking_task_id":str(task.pk), "quantity":"2"}, key="PACK-RETRY", expected=200)["lines"]) == 1
    post("packages", package["id"], "seal", {"seal_number":"ACTUAL-SEAL"}, expected=400)
    client.force_authenticate(user=verifier)
    post("packages", package["id"], "seal", {"seal_number":"ACTUAL-SEAL"}, expected=200)
    client.force_authenticate(user=operator)
    dispatch = post("orders", order.pk, "create-dispatch", {"package_ids":[package["id"]], "delivery_address_id":str(address.pk)})
    post("dispatches", dispatch["id"], "approve", expected=200)
    post("dispatches", dispatch["id"], "load", expected=200)
    post("dispatches", dispatch["id"], "dispatch", expected=200)
    line_id = dispatch["lines"][0]["id"]
    delivery = post("dispatches", dispatch["id"], "delivery", {"recipient_name":"Real synthetic recipient", "proof_type":"SIGNED_POD", "signature_ref":"fixture-signed-evidence", "delivery_lines_data":[{"dispatch_line_id":line_id, "accepted_quantity":"2", "rejected_quantity":"0", "damaged_quantity":"0", "missing_quantity":"0"}]})
    assert delivery["recipient_name"] == "Real synthetic recipient"
    order.refresh_from_db()
    assert order.status == SalesOrder.Status.DELIVERED


def test_no_role_user_cannot_read_or_create_sales_documents(world):
    user = User.objects.create_user(username="hq-sales-no-role", tenant=world["tenant"])
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get("/api/sales/orders/").status_code == 403
    assert client.post("/api/sales/orders/", {}, format="json").status_code == 403
