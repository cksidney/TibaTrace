# Procurement RBAC Matrix

This document defines the Role-Based Access Control (RBAC) matrix and the strict Segregation of Duties (SoD) enforced within the DawaTrace Procurement subsystem.

## Governing Principles

1. **Segregation of Duties (SoD)**: A single individual cannot independently request, authorize, receive, and approve payment for goods.
2. **Clinical Authority Override**: Only users with explicit clinical/quality designations can release quarantined or high-risk products into general inventory.
3. **Tenant Boundary**: All roles and permissions are strictly bounded by the `Tenant` context.

## Roles Defined

- **Procurement Requester**: Typically a branch manager, pharmacist, or department head. Requests goods based on demand.
- **Procurement Approver**: Typically a senior procurement manager, finance controller, or clinical director. Approves financial commitments.
- **Receiving Officer**: Warehouse staff or clinical receiver physically accepting and verifying goods against a PO.
- **Quality Inspector**: A pharmacist or designated quality officer responsible for inspecting temperature excursions, checking expiries, and releasing or quarantining batches.
- **Supplier Manager**: Vendor management team responsible for onboarding, verifying licences, and setting up pricing agreements.

## Access Control Matrix

| Domain Action | Requester | Approver | Receiver | Inspector | Supplier Mgr | SoD / Invariant Checks |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Supplier Onboarding** | ❌ | ❌ | ❌ | ❌ | ✅ | Must provide verification evidence. |
| **Supplier Approval** | ❌ | ✅ | ❌ | ❌ | ❌ | Approver cannot be the onboarder. |
| **Supplier Suspension** | ❌ | ✅ | ❌ | ❌ | ✅ | Triggers block on all draft POs. |
| **Create Requisition** | ✅ | ❌ | ❌ | ❌ | ❌ | Bound to specific requesting branch. |
| **Approve Requisition** | ❌ | ✅ | ❌ | ❌ | ❌ | **CRITICAL:** Requester ≠ Approver. |
| **Convert Req to PO** | ✅ | ✅ | ❌ | ❌ | ❌ | Automatically links pricing agreements. |
| **Approve PO** | ❌ | ✅ | ❌ | ❌ | ❌ | Supplier must be ACTIVE/APPROVED. |
| **Start Goods Receipt** | ❌ | ❌ | ✅ | ❌ | ❌ | PO must be SENT or APPROVED. |
| **Receive PO Lines** | ❌ | ❌ | ✅ | ❌ | ❌ | Strict over-receipt locking enforced. |
| **Capture Batches** | ❌ | ❌ | ✅ | ✅ | ❌ | Expiry and manufacturer batch required. |
| **Quality Disposition** | ❌ | ❌ | ❌ | ✅ | ❌ | Mandatory for temperature excursions. |
| **Initiate Return** | ❌ | ❌ | ✅ | ✅ | ❌ | Linked to valid GRN and supplier. |

## Concurrency and Locking Strategy

To complement RBAC, concurrent operational risks are mitigated via pessimistic locking:
- **`receive_line` Lock**: When a Receiving Officer receives a line, a database-level `select_for_update` lock is acquired on the `PurchaseOrderLine`. This prevents two receivers (or two requests) from concurrently receiving quantities that would exceed the PO limit.

## System Auditing

Every action mapped above is recorded as a Domain Event (e.g., `SupplierApproved`, `PurchaseOrderApproved`, `BatchReleased`) carrying the `actor_id` and the `tenant_id` to ensure absolute non-repudiation.
