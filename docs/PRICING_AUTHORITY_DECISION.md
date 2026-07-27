# Which price table is authoritative?

**Status: answered by evidence, 2026-07-27. Both tables are real, they serve
different channels, and a third path — the till — consults neither.**

The question was which of `pricing.PriceBookEntry` and `sales.PriceListEntry` is
the live price table, because the first is versioned and guarded and the second
was writable with no controls. Tracing what actually charges money settles it.

An earlier draft of this document said `PriceListEntry` is "read by nothing
outside `apps/sales`" and treated that as evidence it was legacy. The statement
was true and the inference was wrong: it is read *inside* `apps/sales`, by the
code that prices every quotation and sales order.

## What each one does

### `sales.PriceListEntry` — live, business-to-business

`apps/sales/services.py` prices quotation and sales-order lines from it, in this
order: a `CustomerPriceAgreement` if one exists, else the customer's assigned
price list, else the tenant's default active list, else `sku.base_price`. It
honours quantity breaks (`minimum_quantity__lte`), effective dating, and layers
`PromotionRule` on top.

This is not legacy. It is the only server-side pricing logic in the codebase
that produces a figure anyone is billed for.

### `pricing.PriceBookEntry` — built, guarded, and wired to nothing

Versioned, immutable once published, effective-dated, resolved through a total
precedence order that fails closed on ambiguity, with an `AppliedPriceSnapshot`
carrying the resolution trace for every charged line.

Its only consumer is `apps/pricing/api/views.py`, which exposes a resolution
endpoint that answers questions about it. Nothing calls `PriceCatalogue.price()`
outside that endpoint. No dispensing, sale or payment path reads it.

So the guarded engine is the one that is not connected, and the unguarded table
is the one doing the work — the reverse of what the original framing assumed.

### The till — neither

`amount_due` on a dispensing payment arrives **in the request body**.
`PaymentIntentService.create` validates only that it is not negative, then
records it. No price table is consulted, and no server-side figure is compared
against what the client sent.

So the amount a patient pays is whatever the POS says it is. A bug in the
client, a stale cached price, or a modified request produces a payment the
server accepts and reconciles against. This is the substantive finding, and it
is larger than the question this document was opened to answer.

## What follows

1. **`sales` pricing stays writable.** It maintains live B2B prices; making it
   read-only would stop price maintenance. `WritablePricingViewSet` in
   `apps/sales/api/views.py` holds that exception deliberately. What it needs is
   governance — approval and audit on price changes — not removal.

2. **The dispensing payment path should derive its own figure.** The till should
   propose an amount and the server should price the episode independently and
   refuse a mismatch, rather than accepting the client's number. This is a
   behavioural change: switched on before price books cover the dispensed
   catalogue, tills stop taking payment. It needs a decision on sequencing and a
   migration path for products with no price book entry.

3. **`pricing` is either the destination or dead weight.** If (2) is done by
   wiring `PriceCatalogue` into the payment path, the engine becomes load
   bearing and its guarantees start paying for themselves. If not, it is an
   elaborate unused subsystem and should say so in its own docstring rather than
   be read as the system of record.

## What was closed alongside this

`apps/medicines` exposed twelve fully writable viewsets over the product master;
they are now read-only, with governed creation available through
`MedicineCatalogueService`. `customers` and `sales` had service actions with a
generic `PATCH` beside them — the shape `procurement` had before it was
corrected — and both are now read-only apart from the pricing exception above.

For contrast, and so the remaining gaps are not read as the general state:

- `procurement` viewsets were `ModelViewSet`s with generic `PATCH` and `DELETE`
  alongside their service-routed actions. A `PATCH` approved a purchase order
  without the supplier re-check; a `DELETE` removed the order outright. Now
  read-only with the service actions retained.
- The DRF exception handler did not recognise Django's `ValidationError` or
  `PermissionDenied`, so every service refusal surfaced as a 500. Now 400 and
  403.
- `insurance`, `pricing`, `pos_shift`, `inventory`, `prescription`, `patients`,
  `organizations` and `practitioners` are read-only or service-routed.
