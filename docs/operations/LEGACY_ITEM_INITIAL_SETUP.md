# Initial catalogue and stock setup

Legacy exports are imported into a separate source-review queue. They do not
create clinical medicines, commercial SKUs, published prices, available stock,
or fabricated barcodes. This also supports non-medicine merchandise and services
without misclassifying them as clinical products.

In HQ, select the tenant and open **Medicine catalogue → Initial catalogue &
stock setup**. Positive source balances are shown first; search by name or legacy
code, or switch to all items / negative balances. Select **Complete details**.

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

## Import procedure

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
