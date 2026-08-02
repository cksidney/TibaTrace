# TibaTrace Purchasing, Receiving, Inventory and Warehouse Operations Architecture

> **Superseded by [the TibaTrace End-to-End Guide](TIBATRACE_USER_GUIDE.md) — §3.5 and §5.1 Inventory: FEFO.**
>
> Kept for its engineering detail and history. The guide is authoritative
> for how the system is used; where the two disagree, the guide is right.

## 1. Overview
The TibaTrace Purchasing, Receiving, Inventory and Warehouse subsystem provides complete operational endpoint management across multi-tenant, multi-branch community pharmacies, hospital dispensaries, and distribution centers.

## 2. Core Architectural Principles
- **Append-Only Inventory Ledger**: Stock quantities are projections computed from immutable `InventoryLedgerEntry` postings.
- **Physical-Financial Reconciliation**: 3-Way matching reconciles Purchase Orders, Goods Received Notes, and Supplier Invoices before Accounts Payable posting.
- **FEFO Allocation & Quality Gating**: Expired, recalled, damaged, or quarantined stock cannot be allocated for sale or dispensing.
- **In-Transit Inventory Control**: Inter-branch transfers place stock into in-transit status during dispatch; destination balances increase only upon verified scan-to-receive confirmation.

## 3. End-to-End Procurement Lifecycle
```text
Demand Identified → Requisition → RFQ & Quotation Award → Approved PO → Receiving Session Scan-to-Receive → Immutable GRN → Quality Inspection → 3-Way Match → Accounts Payable
```
