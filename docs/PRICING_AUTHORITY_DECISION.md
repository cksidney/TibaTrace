# Which price table is authoritative?

**Status: open. Needs a decision before either table is relied on in production.**

There are two price tables in this repository. One is guarded; the other is not.
Nothing distinguishes them by name, and a reader coming to the code fresh would
reasonably assume either is the real one.

## What exists

### `pricing.PriceBookEntry`

- Versioned. A published version is immutable; changing a price creates a new
  version rather than editing a live one.
- Effective-dated, with the service date driving resolution so a backdated sale
  prices at the date of service.
- Resolved through `PriceResolutionService`, which applies a total precedence
  order and **fails closed on ambiguity** rather than picking between two
  equally-ranked sources.
- Every charged line writes an `AppliedPriceSnapshot` carrying the price, the
  source and the full resolution trace.
- Exposed read-only at `/api/pricing/`.

This is what `PriceCatalogue.price()` reads. It is the path the POS and the
resolution endpoint use.

### `sales.PriceListEntry`

- No versioning and no immutability.
- Writable through `/api/sales/` by `POST`, `PUT`, `PATCH` and `DELETE`.
- No approval step, no audit of who changed a price or why.
- Read by nothing outside `apps/sales`. Verified by search: no module in
  `apps/` other than `apps/sales` references it.

So a `PATCH` on a sales price-list entry changes a price with none of the
controls above — and changes a price that nothing currently charges from. It is
an unguarded money surface that happens to be inert.

## Why this needs deciding rather than fixing

The three plausible answers imply materially different work, and picking wrong
is worse than waiting.

1. **`PriceList` is legacy.** Then the sales price viewsets should become
   read-only and a migration path to price books is needed. Roughly a
   five-minute change plus a migration plan.

2. **`PriceList` is the real one and `pricing` is the newcomer.** Then the
   pricing engine is the thing that is not wired in, the resolution endpoint is
   answering from the wrong table, and the immutability work needs moving.

3. **Both are intended, for different purposes.** Then the boundary needs
   stating in code and in this document, because at present nothing marks which
   is which and the next person to add a price will guess.

Making the sales viewsets read-only is correct under (1) and actively wrong
under (2), which is why it has not been done.

## Related, and now closed

`apps/medicines` exposed twelve fully writable viewsets covering the product
master. Those are now read-only. Nothing in the repository wrote through them —
the government-catalogue selection endpoint is a separate view and the HQ
catalogue screens only read — and governed creation already exists in
`MedicineCatalogueService`, which is where a write should go when a UI needs
one. `customers` and `sales` were the procurement shape (service actions with a
generic PATCH beside them) and are read-only too.

`sales.PriceList` and `sales.PriceListEntry` are the exception and remain
writable, because closing them *is* the decision below. `WritablePricingViewSet`
in `apps/sales/api/views.py` exists solely to hold that exception, and
`tests/test_catalogue_write_governance.py::TestPricingIsStillWritableOnPurpose`
fails if someone closes it without answering this document.

## What has already been closed

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
