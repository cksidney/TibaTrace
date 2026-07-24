# Sales Returns

## Overview
Sales Returns govern customer return requests, quality inspections, credit eligibility, and restock authorization within `backend/apps/sales/services.py` (`SalesReturnService`).

## Return Workflow
1. **Return Authorization Request**: `request_return()` creates a `SalesReturnAuthorization` (`UNDER_REVIEW`) and associated `SalesReturnLine` records. Validates that return quantity does not exceed delivered quantity (`delivered_quantity`).
2. **Approval**: `approve_return()` transitions request to `APPROVED` for customer item return.
3. **Physical Receipt & Inspection**: `receive_return()` records received quantities and physical condition checks (`condition`, `temperature_evidence`, `expiry_check`, `quality_disposition`).
4. **Restock Authorization**: If quality disposition is `RELEASED` and item is restock-eligible, an `InventoryLedgerService.post_entry()` of type `RETURN` is posted to return stock to available inventory balances.
5. **Customer Credit Posting**: Approved return lines update `SalesOrderLine.returned_quantity` and trigger eligibility for Accounts Receivable credit note issuance.
