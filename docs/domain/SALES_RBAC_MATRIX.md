# Sales RBAC Matrix

## Overview
The Sales RBAC Matrix defines Role-Based Access Control permissions and Segregation of Duties (SoD) enforcement across Customer Governance and Sales & Fulfilment.

## Role Definitions
- **Sales Rep / Order Entry**: Creates quotations and draft sales orders.
- **Sales Manager**: Approves customer governance records, pricing agreements, quotations, and sales order approvals.
- **Credit Controller**: Evaluates credit limits, manages customer holds (`place_hold`, `release_hold`), and approves credit overrides.
- **Warehouse Picker / Packer**: Executes picking tasks, records picks, opens packing sessions, and seals packages.
- **Logistics / Dispatch Manager**: Creates dispatch orders, approves transport releases, loads packages, and dispatches shipments.
- **Quality Officer**: Inspects sales return lines and authorizes restock dispositions.

## Permission Matrix

| Operation | Sales Rep | Sales Manager | Credit Controller | Warehouse Operative | Quality Officer |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Create Customer** | ✓ | ✓ | — | — | — |
| **Approve / Activate Customer** | — | ✓ | — | — | — |
| **Create Quotation** | ✓ | ✓ | — | — | — |
| **Approve Quotation** | — | ✓ | — | — | — |
| **Create Sales Order** | ✓ | ✓ | — | — | — |
| **Approve Sales Order** | — | ✓ | ✓ | — | — |
| **Place / Release Holds** | — | — | ✓ | — | — |
| **Execute Pick & Pack** | — | — | — | ✓ | — |
| **Approve & Dispatch Order**| — | — | — | ✓ | — |
| **Confirm Delivery** | — | — | — | ✓ | — |
| **Inspect & Restock Return**| — | — | — | — | ✓ |

## Segregation of Duties (SoD) Rules
1. **Self-Approval Denial**: Order creator cannot approve their own sales order if order total exceeds threshold.
2. **Hold Override Restriction**: Sales reps cannot release financial `CREDIT` or compliance `COMPLIANCE` holds.
3. **Dispatch Isolation**: Users executing picking cannot approve dispatch orders without supervisory role.
