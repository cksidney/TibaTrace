# Quotation Lifecycle

## Overview
Quotations represent formal commercial offers issued to customers prior to sales order commitment. Quotation management is implemented in `backend/apps/sales/services.py` via `QuotationService`.

## Lifecycle State Machine
```
[DRAFT] -> [SUBMITTED] -> [APPROVED] -> [SENT] -> [ACCEPTED] -> [CONVERTED]
   │          │               │           │          │
   └──────────┴───────────────┴───────────┴──────────┴─> [REJECTED] / [CANCELLED] / [EXPIRED]
```

### States and Transitions
- **`DRAFT`**: Initial creation state. Lines can be added via `add_quotation_line()`.
- **`SUBMITTED`**: Submitted for internal sales management review via `submit_quotation()`.
- **`APPROVED`**: Formally approved by authorized approver via `approve_quotation()`.
- **`SENT`**: Dispatched to customer via `send_quotation()`, recording `sent_at`.
- **`ACCEPTED`**: Accepted by customer via `accept_quotation()`, recording `accepted_at`.
- **`CONVERTED`**: Converted to a formal `SalesOrder` via `convert_quotation()`.
- **`REJECTED`**: Rejected internally or by customer via `reject_quotation()`. Double-conversion is strictly prevented.

## Revisions and Auditing
Quotations support immutable versioning via `QuotationRevision`:
- Increments `revision` counter on the parent `Quotation`.
- Captures `changed_fields`, `previous_values`, `new_values`, `reason`, and `actor`.

## Stock Reservation Policy
Quotations **never** reserve inventory. Stock reservations occur exclusively when an approved `SalesOrder` invokes `SalesReservationService`.
