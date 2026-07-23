# Inventory RBAC Matrix

The Inventory module introduces several roles required to maintain the separation of duties between stock management, financial liability, and physical operations.

## Roles

1. **Inventory Manager**: Oversees all branch inventory, can trigger stocktakes, and approve variances.
2. **Stock Controller**: Handles day-to-day stock movement (transfers, receiving, issuing) and data entry for stocktakes.
3. **Pharmacist**: Has clinical oversight over expiry, recalls, and quarantine operations.
4. **Read-Only Auditor**: Can view ledgers, balances, and stock movement history but cannot mutate data.

## Permission Matrix

| Operation | Inventory Manager | Stock Controller | Pharmacist | Auditor |
| --- | --- | --- | --- | --- |
| View Balances | ✅ | ✅ | ✅ | ✅ |
| View Ledger | ✅ | ✅ | ✅ | ✅ |
| Create Transfer | ✅ | ✅ | ❌ | ❌ |
| Approve Transfer | ✅ | ❌ | ❌ | ❌ |
| Dispatch/Receive Transfer | ✅ | ✅ | ❌ | ❌ |
| Open Stocktake | ✅ | ❌ | ❌ | ❌ |
| Record Count | ✅ | ✅ | ✅ | ❌ |
| Approve Variances | ✅ | ❌ | ❌ | ❌ |
| Execute Adjustment | ✅ | ❌ | ❌ | ❌ |
| Move to Quarantine | ✅ | ❌ | ✅ | ❌ |
| Process Recalls | ✅ | ❌ | ✅ | ❌ |
| Manage Locations | ✅ | ❌ | ❌ | ❌ |

*Note: In the initial implementation, Django superusers and tenant administrators act as Inventory Managers.*
