from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.sales.models import SalesOrder, SalesOrderAllocation, SalesOrderHold, SalesOrderLine
from apps.sales.services import (
    DeliveryService,
    DispatchService,
    InvoiceEligibilityService,
    PackingService,
    PickingService,
    PickingWaveService,
    SalesAllocationService,
    SalesApprovalService,
    SalesCancellationService,
    SalesOrderService,
    SalesReservationService,
    SalesReturnService,
)


@pytest.mark.django_db
class TestSalesOrdersAndFulfillment:
    @pytest.fixture
    def sales_order(self, tenant_a, branch, active_customer, sku, test_user):
        so = SalesOrderService.create_sales_order(
            tenant=tenant_a,
            branch=branch,
            customer=active_customer,
            currency="KES",
            salesperson=test_user,
        )
        SalesOrderService.add_order_line(
            sales_order=so,
            sku=sku,
            requested_quantity=Decimal("10"),
            unit="EA",
            pricing_data={
                "base_unit_price": Decimal("50.00"),
                "agreed_unit_price": Decimal("50.00"),
                "discount_amount": Decimal("0.00"),
                "discount_percentage": Decimal("0.00"),
                "price_list_ref": "",
            },
        )
        return so

    @pytest.fixture
    def allocated_order(self, sales_order, test_user, stocked_inventory):
        SalesOrderService.submit_order(sales_order=sales_order)
        SalesApprovalService.approve_order(
            sales_order=sales_order,
            approver=test_user,
        )
        SalesReservationService.reserve_order(
            sales_order=sales_order,
            actor=test_user,
        )
        return SalesAllocationService.allocate_order(
            sales_order=sales_order,
            actor=test_user,
        )

    @pytest.fixture
    def verified_pick(
        self,
        allocated_order,
        test_user,
        verifier_user,
        tenant_a,
        branch,
    ):
        line = allocated_order.lines.get()
        allocation = SalesOrderAllocation.all_objects.get(sales_order_line=line)
        wave = PickingWaveService.create_wave(
            tenant=tenant_a,
            branch=branch,
            created_by=test_user,
        )
        wave = PickingWaveService.release_wave(wave=wave)
        task = PickingService.create_picking_task(
            tenant=tenant_a,
            sales_order=allocated_order,
            sales_order_line=line,
            allocation=allocation,
            source_location=allocation.location,
            sku=line.sku,
            batch=allocation.inventory_batch,
            requested_quantity=allocation.quantity,
            picking_wave=wave,
        )
        task = PickingService.assign_task(task=task, picker=test_user)
        task = PickingService.start_task(task=task)
        task = PickingService.record_pick(
            task=task,
            picked_quantity=allocation.quantity,
        )
        task = PickingService.verify_pick(task=task, verifier=verifier_user)
        allocated_order.refresh_from_db()
        line.refresh_from_db()
        return allocated_order, line, allocation, task

    def test_sales_order_lifecycle(self, sales_order, test_user):
        assert sales_order.status == "DRAFT"

        sales_order = SalesOrderService.submit_order(sales_order=sales_order)
        assert sales_order.status == "SUBMITTED"

        sales_order = SalesApprovalService.approve_order(
            sales_order=sales_order,
            approver=test_user,
        )
        assert sales_order.status == "APPROVED"

        hold = SalesApprovalService.place_hold(
            sales_order=sales_order,
            hold_type=SalesOrderHold.HoldType.CREDIT,
            reason="Payment pending",
            placed_by=test_user,
        )
        sales_order.refresh_from_db()
        assert sales_order.status == "ON_HOLD"

        SalesApprovalService.release_hold(
            hold=hold,
            released_by=test_user,
            release_reason="Payment received",
        )
        sales_order.refresh_from_db()
        assert sales_order.status == "APPROVED"

    def test_reservation_service(
        self,
        sales_order,
        test_user,
        stocked_inventory,
    ):
        SalesOrderService.submit_order(sales_order=sales_order)
        SalesApprovalService.approve_order(sales_order=sales_order, approver=test_user)

        sales_order = SalesReservationService.reserve_order(
            sales_order=sales_order,
            actor=test_user,
        )

        assert sales_order.status == "RESERVED"
        assert sales_order.lines.get().reserved_quantity == Decimal("10")

    def test_allocation_service(self, allocated_order):
        assert allocated_order.status == "ALLOCATED"
        allocation = SalesOrderAllocation.all_objects.get(
            sales_order_line=allocated_order.lines.get(),
        )
        assert allocation.quantity == Decimal("10")
        assert allocation.inventory_reservation_id is not None

    def test_picking_service(self, verified_pick):
        sales_order, line, _, task = verified_pick
        assert task.status == "VERIFIED"
        assert line.picked_quantity == Decimal("10")
        assert sales_order.status == "PICKED"

    def test_packing_service(
        self,
        verified_pick,
        test_user,
        verifier_user,
        tenant_a,
        branch,
    ):
        sales_order, line, allocation, task = verified_pick
        session = PackingService.create_session(
            tenant=tenant_a,
            branch=branch,
            sales_order=sales_order,
            packer=test_user,
        )
        package = PackingService.create_package(
            session=session,
            sales_order=sales_order,
            package_type="BOX",
            packer=test_user,
        )
        PackingService.pack_line(
            package=package,
            sales_order_line=line,
            picking_task=task,
            sku=line.sku,
            batch=allocation.inventory_batch,
            quantity=Decimal("10"),
            unit="EA",
        )
        package = PackingService.seal_package(
            package=package,
            seal_number="SEAL-100",
            verifier=verifier_user,
        )
        assert package.status == "SEALED"

    def test_dispatch_and_delivery(
        self,
        verified_pick,
        test_user,
        verifier_user,
        tenant_a,
        branch,
        active_customer,
        delivery_address,
    ):
        sales_order, line, allocation, task = verified_pick
        session = PackingService.create_session(
            tenant=tenant_a,
            branch=branch,
            sales_order=sales_order,
            packer=test_user,
        )
        package = PackingService.create_package(
            session=session,
            sales_order=sales_order,
            delivery_address=delivery_address,
            packer=test_user,
        )
        PackingService.pack_line(
            package=package,
            sales_order_line=line,
            picking_task=task,
            sku=line.sku,
            batch=allocation.inventory_batch,
            quantity=Decimal("10"),
            unit="EA",
        )
        package = PackingService.seal_package(
            package=package,
            seal_number="SEAL-DISPATCH",
            verifier=verifier_user,
        )
        sales_order.refresh_from_db()
        line.refresh_from_db()
        dispatch = DispatchService.create_dispatch(
            tenant=tenant_a,
            branch=branch,
            customer=active_customer,
            delivery_address=delivery_address,
            sales_order=sales_order,
            created_by=test_user,
        )
        d_line = DispatchService.add_dispatch_line(
            dispatch=dispatch,
            sales_order_line=line,
            package=package,
            sku=line.sku,
            batch=allocation.inventory_batch,
            quantity=Decimal("10"),
            unit="EA",
            source_location=allocation.location,
        )
        dispatch = DispatchService.approve_dispatch(
            dispatch=dispatch,
            approver=test_user,
        )
        dispatch = DispatchService.load_dispatch(
            dispatch=dispatch,
            packages=[package],
            loaded_by=test_user,
        )
        dispatch = DispatchService.dispatch_order(
            dispatch=dispatch,
            dispatched_by=test_user,
        )
        assert dispatch.status == "DISPATCHED"

        delivery_lines_data = [
            {
                "dispatch_line_id": d_line.pk,
                "accepted_quantity": Decimal("10"),
                "rejected_quantity": Decimal("0"),
            }
        ]
        DeliveryService.confirm_delivery(
            dispatch=dispatch,
            recipient_name="John Doe",
            proof_type="SIGNATURE",
            recorded_by=test_user,
            delivery_lines_data=delivery_lines_data,
        )

        sales_order.refresh_from_db()
        assert sales_order.status == "DELIVERED"

    def test_sales_return_service(
        self,
        sales_order,
        active_customer,
        test_user,
        verifier_user,
    ):
        line = sales_order.lines.get()
        SalesOrderLine.all_objects.filter(pk=line.pk).update(
            reserved_quantity=Decimal("10"),
            allocated_quantity=Decimal("10"),
            picked_quantity=Decimal("10"),
            packed_quantity=Decimal("10"),
            dispatched_quantity=Decimal("10"),
            delivered_quantity=Decimal("10"),
            status=SalesOrderLine.Status.DELIVERED,
        )
        SalesOrder.all_objects.filter(pk=sales_order.pk).update(
            status=SalesOrder.Status.DELIVERED,
        )
        sales_order.refresh_from_db()
        line.refresh_from_db()
        lines_data = [
            {
                "sales_order_line_id": str(line.pk),
                "sku_id": str(line.sku_id),
                "quantity": Decimal("5"),
            }
        ]
        return_auth = SalesReturnService.request_return(
            sales_order=sales_order,
            customer=active_customer,
            reason="Damaged",
            requested_by=test_user,
            lines_data=lines_data,
        )

        return_auth = SalesReturnService.approve_return(
            return_auth=return_auth,
            approver=verifier_user,
        )
        SalesReturnService.receive_return(
            return_auth=return_auth,
            received_quantities={str(return_auth.lines.get().pk): Decimal("5")},
            received_by=test_user,
        )

        line.refresh_from_db()
        assert line.returned_quantity == Decimal("5")

    def test_sales_cancellation_service(self, sales_order, test_user):
        sales_order.status = "ALLOCATED"
        sales_order.save()

        SalesCancellationService.cancel_order(sales_order=sales_order, reason="Customer requested", actor=test_user)
        sales_order.refresh_from_db()
        assert sales_order.status == "CANCELLED"

    def test_sales_cancellation_dispatched_fails(self, sales_order, test_user):
        sales_order.status = "DISPATCHED"
        sales_order.save()

        with pytest.raises(ValidationError, match="Dispatched orders cannot be cancelled"):
            SalesCancellationService.cancel_order(sales_order=sales_order, reason="Changed mind", actor=test_user)

    def test_invoice_eligibility_service(self, sales_order):
        sales_order.invoice_policy = "ON_DELIVERY"
        sales_order.status = "DELIVERED"
        sales_order.save()

        eligible = InvoiceEligibilityService.evaluate_eligibility(sales_order=sales_order)
        assert eligible is True
