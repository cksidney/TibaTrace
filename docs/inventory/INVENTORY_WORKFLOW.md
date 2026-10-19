# Inventory operating workflow

Opening stock starts with a tenant's own item list. An upload creates source
evidence only. Historical source quantities cannot become physical inventory.

1. In HQ, open Inventory → initial item setup and download the item-list template.
   Upload the tenant's corrected codes, names and selling units. Review the
   import preview before applying it.
2. Download the populated opening stocktake sheet. Count actual shelves, record
   today's date and the real medicine batches and expiry dates, then upload the
   completed sheet. Old or already staged sheets are refused.
3. Confirm item kind, pack/unit identity, acquisition cost per selling unit,
   selling price and tax category. Medicines also require the reviewed medicine
   reference. Missing evidence blocks staging.
4. Stage actual stock into compatible quarantine. Review and publish the linked
   price version. A separate authorized operator must release opening custody
   into the correct saleable location. Neither import nor counting enables sale.

Discarded imports remain available as source/audit evidence, are removed from
active onboarding, cannot be revived through review, and cannot block a corrected
upload with the same legitimate item codes. Sources with staged stock cannot be
discarded; subsequent corrections require governed stock workflows.

## Receiving and quality

Both scanned and manual receiving book delivered base units against the purchase
order and leave them unaccepted. Scanned receiving posts physical quarantine
custody. Non-expiring supplies use internal custody lots; expiry-tracked items
still require a valid expiry.

A named, authorized quality reviewer independent of the receiver records an
outcome and evidence. A hold can be superseded by an explicit, numbered
reinspection with new evidence. Earlier evidence remains immutable; a rejection
cannot be overturned through routine reinspection.

Release requires an approving current decision, an independent authorized
releaser, current supplier qualifications, compatible custody, and no expiry or
recall hold. Supplier-return claims reduce the quantity eligible for release;
posted returns reduce physical custody. A shortfall in staged quarantine never
creates replacement receipts. API release includes its saleable destination and
uses a retry key to avoid repeated acceptance or movement.

## Units, allocation and reservations

In Inventory → replenishment and pack units, configure the exact barcode and
number of stock/selling units in one scanned pack. Conversion happens once at
receiving or POS intake and is retained as evidence. Manual quantities already
represent base units. Deactivated mappings are refused.

FEFO selects only eligible released, unrecalled stock in active saleable custody.
Reservations record the actual batch allocations in the immutable ledger.
Fulfilment, cancellation and expiry consume only the remaining per-batch reserved
quantity. Partial fulfilment does not prevent recovery. Scheduled expiry cleanup
only acts on reservations with an explicit elapsed expiry time.

Physical on-hand is the sum of physical movement deltas. Reserved quantity is
reservation deltas minus reservation releases, including fulfilment. Reservation
entries never increase physical stock. Reconciliation and repair use this same
identity and derive availability from custody, quality, expiry and recall holds.
A PostgreSQL repair locks source/projection tables and fails safely if busy;
invalid source events require investigation rather than a projection rewrite.

## Replenishment and warehouse work

Configure verified safety stock, reorder point, target level, order multiple and
lead days per branch/SKU. No tenant targets are invented. The hourly planner
considers usable stock, pending requisitions/orders, quality-held deliveries and
inbound transfers. It updates or withdraws pending recommendations and prevents
repeat recommendations for unchanged rejected demand.

Reviewing a recommendation creates a submitted purchase requisition. Its
requester cannot approve it; supplier selection, procurement approval, ordering
and receiving continue through their existing governed workflows. A changed
stock position requires a refreshed review.

Warehouse tasks link to real receipt, batch, picking, packing, dispatch,
transfer or stocktake documents. Assign an authorized tenant operator, start the
task, perform the source workflow and record completion evidence. Completion
checks the source outcome and never posts an extra stock movement. Cancellation
does not cancel the source document. Cancelled tasks may reopen with a reason;
completed tasks remain terminal.

## Exceptions and valuation

Adjustments, write-offs, destruction, acquisition costs and transfer shortage
closure require independent approval. HQ displays the item, unit, lot, custody,
current quantities, proposed effect and supporting evidence before a decision.
Acquisition valuation is an operational specific-identification view, with
unknown costs shown as unvalued. Statutory accounting, impairment/NRV policy and
general-ledger posting remain outside the inventory valuation contract.
