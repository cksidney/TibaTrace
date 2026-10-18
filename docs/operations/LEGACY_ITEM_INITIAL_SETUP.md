# Initial catalogue and stock setup

Legacy exports are imported into a separate source-review queue. They do not
create clinical medicines, commercial SKUs, published prices, available stock,
or fabricated barcodes. This also supports non-medicine merchandise and services
without misclassifying them as clinical products.

In HQ, select the tenant and open **Medicine catalogue → Upload items & prepare
stock take**. All imported items are shown, with positive source balances first;
search by name or legacy code, or filter positive / negative balances. Select
**Complete details** to review an item.

## Tenant CSV upload and opening stock take

1. Choose **Upload item list → Download item template**. Save the completed file
   as CSV UTF-8. Keep codes and barcodes as text so leading zeros survive Excel.
2. Fill `item_code`, `item_name`, and `sales_unit` for every row. Optional columns
   are `item_kind`, `pack_description`, `cost_price`, `selling_price`,
   `tax_category`, `barcode`, `master_catalogue_code`, and `source_quantity`.
   Use one row per item, with a unique item code. Omit unverified values.
3. Choose the source-data date and CSV, then **Preview import**. Up to 5,000
   items and 5 MB are accepted per file. Correct any row errors; a file with
   errors writes nothing. **Import validated items** stages the complete file.
4. Choose **Download stock-take sheet** in the confirmation, or choose an item
   source and download it later from the setup panel. The sheet includes every
   eligible item from that source across all pages and ignores table searches.
   Completed and excluded setup items are omitted. Leave item IDs with the sheet.
5. Count physical stock in each item's sales unit. Enter an explicit zero for an
   observed zero balance. For medicines, duplicate the item row for each actual
   batch and enter its batch number, expiry date and quantity. Record the count
   date and notes. Historical balances and prices are omitted for blind counting.
6. Use **Complete details** to enter and review the verified quantities and batch
   details from the worksheet. This release downloads the worksheet; it does not
   bulk-upload completed counts. Existing governed staging, independent release,
   and price publication remain the steps that prepare items for trading.

`item_kind` accepts `MEDICINE`, `SUPPLY`, or `SERVICE`. `tax_category` accepts
`STANDARD`, `ZERO_RATED`, or `EXEMPT`. Prices are per sales unit and accept up to
four decimal places. Source quantities may be negative because they preserve
the old system's evidence; actual counted quantities must be non-negative.
Blank monetary and quantity cells remain distinguishable from reported zero.
Uploaded fields are review candidates and are not marked as confirmed.

Repeating the same canonical file and date returns its existing import and
preserves all manager work, even if the filename or row order changed. A
different upload that reuses an existing item code is rejected for review,
rather than creating a second item. Imports and downloads require the tenant's
`inventory.manage` capability. Neither creates saleable products or posts stock.

An inventory manager can save partial work and return later. Confirm the sales
unit, pack description, price, tax treatment, today's physical count, and item
type. For medicines, confirm the exact national reference and enter each actual
batch, expiry date and quantity. No barcode is required for initial setup.

The original product and stock values remain unchanged, including negative
balances and zero prices. Proposed `TE-…` codes are internal references, not
GTINs. Blank legacy codes receive stable source-row references instead of being
merged by name. Every manager save records the actor and before/after values in
a domain event. Stale edits are rejected with HTTP 409 rather than overwriting
another manager's work. Cross-tenant reads and saves are scoped explicitly.

**Details complete** means ready for catalogue review, not ready to trade.
Governed clinical/manufactured product and package provisioning, branch
assortment, independent price approval/publication, and opening-stock ledger
posting remain separate steps. Expired medicine batches and unreconciled batch
quantities cannot be marked complete. No missing manufacturer, authorization,
composition, batch or expiry is inferred from a similar name.

## Operator-assisted PDF / JSON import

Extract PDF tables, join by exact legacy code (or a unique normalized name for
missing codes), preserve raw rows and PDF page numbers, and reconcile all totals
against the source footer. Include source file SHA-256 digests in provenance.

Run `import_legacy_item_setup SOURCE.json --tenant-slug SLUG --actor-email EMAIL`
for validation only. Add `--apply` after validation. Tenant slug and exact tenant
name must match the source manifest. The import is atomic. Repeating the same
import code and provenance does not duplicate rows or overwrite manager work.

Access to manager saves uses the existing `inventory.manage` capability; this
does not grant catalogue publication or price approval authority. Source records
have no generic create/update/delete API. Both new tables are additive so the
previous application remains compatible for application rollback.

### Re-upload the completed physical count

Use **HQ → Catalogue → Upload items & prepare stock take → Upload completed count sheet**. Keep `item_id` and `expected_updated_at` unchanged, record explicit quantities (including zero) and today's `counted_on`. For medicine stock, duplicate a row for each distinct actual batch and expiry; the batch quantities are summed for that item. Preview validation first, then save. An invalid or stale row rejects the whole upload. Counts update only manager evidence; units, price, medicine mapping, price approval and independent quality release still follow.

Supplies can now be staged from confirmed manager details as nondispensable supply SKUs, without clinical medicine records. Non-expiring supplies receive an explicitly labelled internal custody lot. Services create no physical stock. Select the matching item type and exact sales unit; confirm product, unit, tax and storage before staging. A supplied acquisition cost is approved as part of independent opening-stock release; an omitted cost stays unvalued.
