# Three-Way Matching Data Contract Baseline

## Overview

The `ThreeWayMatch` data contract establishes the baseline for automated financial reconciliation between:

```text
Purchase Order ↔ Goods Receipt ↔ Supplier Invoice
```

## Tracked Variances
* **Quantity Variance**: Difference between PO ordered quantity, GRN accepted quantity, and invoiced quantity.
* **Price Variance**: Difference between PO agreed unit price and supplier invoice unit price.
* **Matching Statuses**: `UNMATCHED`, `MATCHED`, `VARIANCE_FLAGGED`, `ACCEPTED_WITH_VARIANCE`.
