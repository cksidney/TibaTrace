# Dispatch and Delivery

## Overview
Dispatch and Delivery manage outer logistics custody transfer, transport conditions, and electronic proof-of-delivery (ePOD) within `backend/apps/sales`.

## Dispatch Workflow (`DispatchService`)
1. **Dispatch Order Creation**: `create_dispatch()` creates a `DispatchOrder` linked to customer, branch, delivery address, carrier, vehicle registration, and driver details.
2. **Line & Package Loading**: `add_dispatch_line()` adds items with durable idempotency keys (`idempotency_key`). `load_dispatch()` links sealed packages to vehicle loading records (`DispatchPackage`).
3. **Approval & Dispatch Execution**: `approve_dispatch()` approves transport document. `dispatch_order()` changes status to `DISPATCHED`, updates `sales_order_line.dispatched_quantity`, and posts negative `ISSUE` entries to `InventoryLedgerService`.

## Delivery Workflow (`DeliveryService`)
1. **Delivery Confirmation**: `confirm_delivery()` creates a `DeliveryRecord` capturing recipient name, recipient role, contact phone, signature reference (`signature_ref`), photo proof (`photo_ref`), GPS coordinates (`coordinates`), and continuous temperature evidence log (`temperature_evidence`).
2. **Discrepancy & Line Rejection**: Individual delivery lines record `accepted_quantity`, `rejected_quantity`, `damaged_quantity`, and `missing_quantity`. If all items are accepted, status becomes `DELIVERED`; otherwise `PARTIALLY_DELIVERED`.
3. **Delivery Failure**: `record_failed_delivery()` logs failed delivery attempts with explicit failure reasons.
