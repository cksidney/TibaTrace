"""Cash refunds are append-only money facts, independent approval and held custody."""
# ruff: noqa: F811
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from tests.test_pos_retail_transactions import prepare_sale_for_payment, world  # noqa: F401

from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryBalance, InventoryLedgerEntry, InventoryLocation
from apps.platform.reporting.queries import query_report
from apps.pos_shift.cash_control import CashControlService
from apps.pos_shift.models import CashDeclaration, OperatorShift, RegisterSession
from apps.pos_transactions.models import PosTransaction, RetailCashReceipt, RetailCashRefund, RetailRefundLine
from apps.prescription.pos_printing_models import PosPrintDocument

pytestmark = pytest.mark.django_db


def user(tenant, name, capabilities):
    actor = User.objects.create_user(username=name, tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code=name, name=name, capabilities=capabilities)
    UserRole.all_objects.create(tenant=tenant, user=actor, role=role)
    return actor


def paid(world):
    sale = prepare_sale_for_payment(world)
    response = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/cash-settle/",
        {"device_id": "POS-RETAIL-01", "cash_received": "300.00", "idempotency_key": "sale-cash"}, format="json")
    assert response.status_code == 200, response.data
    return response.json()


def refund_request(world, sale, physical=False, quantity="1", key="request-key", **extra):
    payload = {"device_id": "POS-RETAIL-01", "reason": "Customer return", "idempotency_key": key,
        "lines": [{"line_id": sale["lines"][0]["id"], "quantity": quantity, "return_to_stock": physical}]}
    if physical:
        location = InventoryLocation.all_objects.create(tenant=world["tenant"], branch=world["branch"], location_code="RETURN-HOLD",
            name="Returned goods hold", location_type="QUARANTINE", quarantine_capability=True)
        payload["return_location_id"] = str(location.pk)
        payload["lines"][0]["inventory_batch_id"] = sale["lines"][0]["issued_batches"][0]["batch_id"]
    payload.update(extra)
    response = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/request-refund/", payload, format="json")
    return response, payload


def approve(world, sale, request):
    supervisor = user(world["tenant"], "refund-supervisor", ["pos.refund.approve"])
    world["client"].force_authenticate(supervisor)
    response = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/approve-refund/",
        {"refund_request_id": request["id"]}, format="json")
    assert response.status_code == 200, response.data
    world["client"].force_authenticate(world["operator"])


def execute(world, sale, request, key="refund-cash"):
    return world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/cash-refund/",
        {"refund_request_id": request["id"], "device_id": "POS-RETAIL-01", "idempotency_key": key}, format="json")


def test_cash_refund_is_independent_idempotent_and_receipt_linked(world):  # noqa: F811
    sale = paid(world)
    response, payload = refund_request(world, sale)
    assert response.status_code == 201, response.data
    request = response.json()
    assert execute(world, sale, request).status_code == 400
    self_approval = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/approve-refund/", {"refund_request_id": request["id"]}, format="json")
    assert self_approval.status_code == 400
    approve(world, sale, request)
    first = execute(world, sale, request)
    second = execute(world, sale, request)
    assert first.status_code == second.status_code == 200
    assert first.json()["refund_number"] == second.json()["refund_number"]
    assert first.json()["amount"] == "125.00"
    assert first.json()["original_receipt_number"] == sale["receipt"]["receipt_number"]
    assert RetailCashRefund.all_objects.count() == 1
    assert RetailCashReceipt.all_objects.count() == 1
    assert PosTransaction.all_objects.get(pk=sale["id"]).state == "COMPLETED"
    cash = CashControlService.expected_cash(session=world["session"])
    assert cash.expected == Decimal("125.00")
    assert cash.cash_sales == Decimal("250.00") and cash.cash_refunds == Decimal("125.00")
    assert PosPrintDocument.all_objects.filter(document_type="RETAIL_REFUND").count() == 1
    assert not InventoryLedgerEntry.all_objects.filter(source_document_type="POS_RETAIL_REFUND").exists()
    assert execute(world, sale, request, key="different").status_code == 400
    replay = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/request-refund/", payload, format="json")
    assert replay.status_code == 201 and replay.json()["id"] == request["id"]
    with pytest.raises(ValidationError):
        RetailCashRefund.all_objects.update(amount=Decimal("1"))
    with pytest.raises(ValidationError):
        RetailRefundLine.all_objects.delete()


def test_physical_return_stays_in_quarantine_and_never_releases_original_batch(world):  # noqa: F811
    sale = paid(world)
    response, payload = refund_request(world, sale, physical=True)
    assert response.status_code == 201, response.data
    request = response.json()
    approve(world, sale, request)
    response = execute(world, sale, request)
    assert response.status_code == 200, response.data
    holding = InventoryBalance.all_objects.get(location_id=payload["return_location_id"])
    assert holding.on_hand == holding.quarantined == Decimal("1")
    assert holding.available == 0
    assert holding.inventory_batch.quality_status == "RELEASED"  # Other original goods unchanged.
    assert InventoryBalance.all_objects.get(location=world["store"]).on_hand == Decimal("6")
    assert response.json()["lines_snapshot"][0]["disposition"] == "QUARANTINE_PENDING_QUALITY_REVIEW"


def test_pending_refunds_reserve_quantity_and_rejection_releases_it(world):  # noqa: F811
    sale = paid(world)
    first, _ = refund_request(world, sale, quantity="2")
    assert first.status_code == 201
    excessive, _ = refund_request(world, sale, quantity="1", key="excess")
    assert excessive.status_code == 400
    supervisor = user(world["tenant"], "rejector", ["pos.refund.approve"])
    world["client"].force_authenticate(supervisor)
    rejection = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/reject-refund/",
        {"refund_request_id": first.json()["id"], "reason": "Correct the request"}, format="json")
    assert rejection.status_code == 200
    world["client"].force_authenticate(world["operator"])
    corrected, _ = refund_request(world, sale, quantity="2", key="corrected")
    assert corrected.status_code == 201


def test_sales_reports_include_retail_collections_and_completed_refunds(world):  # noqa: F811
    sale = paid(world)
    request, _ = refund_request(world, sale)
    approve(world, sale, request.json())
    assert execute(world, sale, request.json()).status_code == 200
    collections = query_report("sales-period", world["tenant"].pk, world["operator"], None)
    refunds = query_report("sales-refunds", world["tenant"].pk, world["operator"], None)
    assert Decimal(collections.rows[0][4]) == Decimal("250.00")
    assert Decimal(refunds.rows[0][4]) == Decimal("125.00")
    assert collections.rows[0][-1] == refunds.rows[0][-1] == "RETAIL"


def test_retail_reads_deny_no_role_and_scope_ordinary_cashiers(world):  # noqa: F811
    sale = paid(world)
    no_role = user(world["tenant"], "no-retail-role", [])
    world["client"].force_authenticate(no_role)
    assert world["client"].get(f"/api/pos/retail/transactions/{sale['id']}/").status_code == 403
    other = user(world["tenant"], "other-cashier", ["pos.transaction.create"])
    world["client"].force_authenticate(other)
    assert world["client"].get(f"/api/pos/retail/transactions/{sale['id']}/").status_code == 404
    body = world["client"].get("/api/pos/retail/transactions/").json()
    assert (body["results"] if isinstance(body, dict) else body) == []


def test_permission_report_includes_events_from_real_identity_endpoint(world):  # noqa: F811
    operator = world["operator"]
    member = user(world["tenant"], "identity-member", [])
    role = Role.all_objects.create(tenant=world["tenant"], code="RX-READER", name="Reader", capabilities=["dispensing.read"])
    response = world["client"].post(f"/api/identity/users/{member.pk}/set-roles/", {"role_ids": [str(role.pk)]}, format="json",
        HTTP_X_TENANT_ID=str(world["tenant"].pk))
    assert response.status_code == 200, response.data
    result = query_report("sec-permission-changes", world["tenant"].pk, operator, None)
    assert any(row[2] == "IDENTITY_USER_ROLES_UPDATED" and row[3] == "User" for row in result.rows)


def test_refund_uses_current_funded_shift_and_does_not_rewrite_original_session(world):  # noqa: F811
    sale = paid(world)
    request, _ = refund_request(world, sale)
    approve(world, sale, request.json())
    original_session = world["session"]
    original_session.state, original_session.closed_at = "CLOSED", timezone.now()
    original_session.save(update_fields=["state", "closed_at", "updated_at"])
    world["operator_shift"].state = "CLOSED"
    world["operator_shift"].save(update_fields=["state", "updated_at"])
    current = RegisterSession.all_objects.create(tenant=world["tenant"], register=world["register"],
        business_day=world["business_day"], opened_by=world["operator"], state="OPEN")
    shift = OperatorShift.all_objects.create(tenant=world["tenant"], register_session=current, operator=world["operator"], state="OPEN")
    assert execute(world, sale, request.json()).status_code == 400  # Unfunded drawer.
    CashDeclaration.all_objects.create(tenant=world["tenant"], register_session=current, operator_shift=shift,
        kind="OPENING", declared_amount=Decimal("200"), declared_by=world["operator"], confirmed_at=timezone.now())
    response = execute(world, sale, request.json())
    assert response.status_code == 200, response.data
    assert response.json()["register_session"] == str(current.pk)
    assert CashControlService.expected_cash(session=current).expected == Decimal("75")
    assert CashControlService.expected_cash(session=original_session).expected == Decimal("250")


def test_physical_return_refuses_unknown_batch_and_saleable_destination(world):  # noqa: F811
    sale = paid(world)
    response, payload = refund_request(world, sale, physical=True)
    assert response.status_code == 201
    # No stock moves before approval and cash execution.
    assert not InventoryLedgerEntry.all_objects.filter(source_document_type="POS_RETAIL_REFUND").exists()
    payload["idempotency_key"] = "bad-holding"
    payload["return_location_id"] = str(world["store"].pk)
    rejected = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/request-refund/", payload, format="json")
    assert rejected.status_code == 400
    payload["idempotency_key"] = "missing-batch"
    payload["return_location_id"] = response.json()["return_location"]
    payload["lines"][0].pop("inventory_batch_id")
    rejected = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/request-refund/", payload, format="json")
    assert rejected.status_code == 400


def test_refund_actions_require_explicit_authority(world):  # noqa: F811
    sale = paid(world)
    request, _ = refund_request(world, sale)
    ordinary = user(world["tenant"], "refund-no-cap", ["pos.transaction.create"])
    world["client"].force_authenticate(ordinary)
    assert world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/approve-refund/",
        {"refund_request_id": request.json()["id"]}, format="json").status_code == 403
    assert execute(world, sale, request.json()).status_code == 403


def test_refund_idempotency_conflicts_and_revoked_approver_do_not_move_money(world):  # noqa: F811
    sale = paid(world)
    request, payload = refund_request(world, sale)
    payload["reason"] = "Changed under the same key"
    conflict = world["client"].post(f"/api/pos/retail/transactions/{sale['id']}/request-refund/", payload, format="json")
    assert conflict.status_code == 400
    approve(world, sale, request.json())
    supervisor = User.objects.get(username="refund-supervisor")
    supervisor.is_active = False
    supervisor.save(update_fields=["is_active"])
    assert execute(world, sale, request.json()).status_code == 400
    assert RetailCashRefund.all_objects.count() == 0
    assert CashControlService.expected_cash(session=world["session"]).expected == Decimal("250")
