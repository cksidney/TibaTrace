# Sales Invoice Eligibility Contract

## Overview
The Sales Invoice Eligibility Contract defines the exact contractual requirements for when a sales order or dispatch line becomes eligible for financial invoice creation / Accounts Receivable posting (`backend/apps/sales/services.py` via `InvoiceEligibilityService`).

## Invoicing Policies (`InvoicePolicy`)
1. **`ON_ORDER_APPROVAL`**: Invoice eligible immediately upon `SalesOrder` entering `APPROVED` status. Suitable for pro-forma or advance payment orders.
2. **`ON_DISPATCH`**: Invoice eligible when `DispatchOrder` enters `DISPATCHED` status and negative inventory `ISSUE` ledger entries are confirmed.
3. **`ON_DELIVERY`**: Invoice eligible only after `DeliveryRecord` reaches `DELIVERED` or `PARTIALLY_DELIVERED` status with confirmed recipient sign-off.
4. **`ON_ACCEPTANCE`**: Invoice eligible after customer customer acceptance period closes without disputes.

## Eligibility Evaluation Contract
`InvoiceEligibilityService.evaluate_eligibility(*, sales_order)` returns a boolean decision:

```python
if sales_order.invoice_policy == 'ON_ORDER_APPROVAL':
    return sales_order.status in ['APPROVED', 'RESERVED', 'ALLOCATED', 'PICKED', 'PACKED', 'DISPATCHED', 'DELIVERED', 'CLOSED']
elif sales_order.invoice_policy == 'ON_DISPATCH':
    return sales_order.status in ['DISPATCHED', 'DELIVERED', 'CLOSED']
elif sales_order.invoice_policy in ['ON_DELIVERY', 'ON_ACCEPTANCE']:
    return sales_order.status in ['DELIVERED', 'CLOSED']
return False
```

## Anti-Pattern Guarantees
- Orders with active holds (`SalesOrderHold.is_active=True`) are **never** eligible for invoicing.
- Cancelled or rejected orders (`CANCELLED`, `REJECTED`) are **never** eligible for invoicing.
