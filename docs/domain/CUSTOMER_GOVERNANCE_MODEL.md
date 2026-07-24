# Customer Governance Model

## Overview
The Customer Governance Model defines customer counterparties in DawaNexus (`backend/apps/customers`). It separates commercial identities from clinical patients and provides rigorous counterparty compliance, risk profiling, credit terms, and delivery address governance.

## Counterparty Classification
Customers are categorized via `CustomerType`:
- `INDIVIDUAL`: Retail or direct end-user customer
- `PHARMACY`: Retail/community or hospital pharmacy entity
- `HOSPITAL`: Acute care or healthcare provider institution
- `CLINIC`: Outpatient care provider
- `WHOLESALE` / `WHOLE_SALER`: Bulk distributor/re-seller
- `DISTRIBUTOR`: Authorized regional pharmaceutical distributor
- `GOVERNMENT`: Public health authority, MOH, or public procurement body
- `NGO`: Non-governmental healthcare agency / donor project
- `INSURER`: Health maintenance organization / medical insurance provider
- `CORPORATE`: Employer health program or corporate account
- `INTERNAL`: Intra-organization branch or subsidiary

## Governance Lifecycle
Customer approval follows a strict state transition model managed by `CustomerGovernanceService`:
```
[PROSPECTIVE] -> [UNDER_REVIEW] -> [APPROVED] -> [ACTIVE] -> [SUSPENDED] / [BLOCKED] -> [ARCHIVED]
```

### State Transitions
1. **Creation**: Initial status defaults to `UNDER_REVIEW`. Emits `CustomerCreated`.
2. **Approval**: `approve_customer()` moves status from `UNDER_REVIEW` to `APPROVED`, populating `approved_by` and `approved_at`. Emits `CustomerApproved`.
3. **Activation**: `activate_customer()` transitions status from `APPROVED` to `ACTIVE`. Emits `CustomerActivated`.
4. **Suspension**: `suspend_customer()` transitions `ACTIVE` customer to `SUSPENDED`. Sales order creation and approval are blocked. Emits `CustomerSuspended`.
5. **Reactivation**: `reactivate_customer()` returns `SUSPENDED` customer to `ACTIVE`. Emits `CustomerReactivated`.
6. **Blocking**: `block_customer()` immediately blocks any non-archived customer. Emits `CustomerBlocked`.

## Credit Policy Evaluation
`CustomerCreditPolicyService.evaluate_order(*, customer, order_total)` enforces financial risk policy:
- Customer status must be `ACTIVE`.
- Customer credit status must not be `CREDIT_HOLD` or `BLOCKED`.
- Order value must not exceed customer's `credit_limit` (when configured > 0).

## Delivery Addresses & Commercial Profiles
- **`CustomerDeliveryAddress`**: Stores geo-located delivery locations, route zones, cold-chain capability flags (`cold_chain_capable`), and controlled substance receipt eligibility (`controlled_medicine_capable`).
- **`CustomerCommercialProfile`**: Links a customer to default price lists (`price_list`), default branch (`default_branch`), tax treatment, credit limits, order value thresholds, and SKU restrictions (`allowed_sku_categories`, `blocked_skus`).
