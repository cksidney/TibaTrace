# Sales Order Lifecycle

## Overview
A `SalesOrder` represents a binding commercial agreement to supply pharmaceutical goods to a customer.

## Complete Lifecycle State Machine
```
[DRAFT] -> [SUBMITTED] -> [APPROVED] -> [RESERVED] -> [ALLOCATED] -> [PICKED] -> [PACKED] -> [DISPATCHED] -> [DELIVERED] -> [CLOSED]
   │          │               │             │             │            │          │             │
   └──────────┴───────────────┴─────────────┴─────────────┴────────────┴──────────┴─────────────┴──> [ON_HOLD] / [BACKORDERED] / [CANCELLED]
```

## Detailed States
1. **`DRAFT`**: Order created via `SalesOrderService.create_sales_order()`. Lines added via `add_order_line()`.
2. **`SUBMITTED`**: Submitted for customer credit & compliance evaluation (`submit_order()`).
3. **`APPROVED`**: Customer credit check passed and authorized by sales manager (`SalesApprovalService.approve_order()`).
4. **`ON_HOLD`**: Order holds placed via `place_hold()` (CREDIT, COMPLIANCE, QUALITY, MANUAL_REVIEW). All fulfilment operations are blocked while active holds exist. Released via `release_hold()`.
5. **`RESERVED`**: Inventory soft-reserved across branch stock via `SalesReservationService.reserve_order()`.
6. **`BACKORDERED`**: Partial stock availability results in backordering unfulfilled quantities.
7. **`ALLOCATED`**: FEFO allocation assigns specific physical `InventoryBatch` instances via `SalesAllocationService.allocate_order()`.
8. **`PICKED`**: Warehouse picking tasks executed and verified via `PickingService`.
9. **`PACKED`**: Items packed into sealed containers with seal numbers via `PackingService`.
10. **`DISPATCHED`**: Dispatched on carrier/vehicle via `DispatchService.dispatch_order()`. Inventory ledger entry (`ISSUE`) posted.
11. **`DELIVERED`**: Recipient sign-off and delivery proof captured via `DeliveryService.confirm_delivery()`.
12. **`CANCELLED`**: Order cancelled via `SalesCancellationService.cancel_order()`. Orders that are `DISPATCHED` or `DELIVERED` cannot be cancelled (must use sales return workflow).
