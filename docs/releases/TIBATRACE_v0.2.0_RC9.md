# TibaTrace v0.2.0-rc9

Release candidate `0.2.0-rc9` adds governed barcode-assisted stock transfer
and receipt workflows on top of the RC8 Reports release.

## Included changes

- added parsing for human-readable GS1 DataMatrix application identifiers,
  registered barcodes, and exact SKU codes;
- resolves scans only against released stock at the selected source location,
  rejecting missing or ambiguous tenant-catalogue mappings without fallback;
- increments an existing transfer line or adds one while enforcing the
  authoritative available quantity;
- exposes each SKU's tenant-scoped registered barcode through inventory balance
  and stock-transfer APIs;
- starts receipt counts at zero and verifies each scan against the expected SKU,
  transfer batch, and remaining quantity before incrementing acceptance;
- preserves the requirement for two active locations and released stock before
  opening a transfer request; and
- packages document QR data only when supplied with a server-issued SHA-256
  checksum and authoritative HTTPS validation URL—no client-fabricated proof.

## Deployment

Backend and HQ images must be built by the production-images workflow from the
annotated release tag and deployed by immutable digest. Production retains RC8
as the sole rollback release after RC9 health and UI verification complete.
