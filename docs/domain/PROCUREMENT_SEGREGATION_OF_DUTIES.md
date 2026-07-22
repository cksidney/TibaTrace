# Procurement Segregation of Duties Governance

## Overview

DawaTrace enforces strict segregation of duties across all procurement, receiving, and quality actions:

1. **Requisition vs Approval**: Requisition requester cannot approve their own Purchase Requisition.
2. **Purchasing vs Receiving**: Ordering procurement officer cannot be the sole receiver of goods.
3. **Receiving vs Quality Release**: Receiving clerk cannot release high-risk or quarantined batches without authorized quality/pharmacist review.
4. **Supplier Status Governance**: Requisitions and POs cannot be created for prospective, suspended, or disqualified suppliers.
