# TibaTrace v1.0.0-rc36 — governed workflow closure

Release candidate for API, HQ, worker and beat, paired with signed Windows POS
1.0.5. This includes the deployed rc35 password fix without losing HQ pagination.
Android source changes are included but no Android installer is published until
its approved signing identity is configured.

## Reviewed scope

- Canonical clinical reservation, allocation, preparation and independent final
  check on native tills. Payment/supply/terminal states cannot be manufactured by
  the generic status action. Explicit counselling and collection evidence remain
  mandatory. HQ can originate actual paper prescriptions and priced episodes;
  intake does not imply clinical approval and missing prices do not imply free supply.
- Capability-gated and branch-scoped POS, inventory, pricing and financial reads;
  cashier responses redact clinical details. Identity role changes are audited.
- Receipt-linked, independently approved cash refunds and quarantined physical
  returns; immutable refund receipts, replay binding and current-till reconciliation.
- HQ source-catalogue completion, commerce creation/fulfilment, complete stocktake
  scope/recounts/cancellation, safe paging and scheduled expiry projection upkeep.
- Windows OS-driver printing of authoritative receipts/labels. Spooler acceptance
  is not proof of physical printing; operators must inspect output. No guessed
  cash-drawer pulse is sent. Browser `/pos/` is installer handoff only.
- 56 source-backed report packs, with explicit bounds and non-statutory bases.
  44 other report packs remain unavailable with stated source prerequisites.

## Database and deployment

Four reviewed migrations relative to rc35: inventory 0006 (stocktake scope and
revisions), medicines 0005 (legacy-item completion), pos_transactions 0003
(refund records/constraints), prescription 0016 (refund print-document choice).
No migration seeds credentials, infers real stock or activates source imports.

Deploy only after full backend/application and immutable CI-image checks pass.
Take a verified predeployment database backup. Pin API/worker/beat and HQ to the
same source revision using CI digests; retain rc35 images, directory and runtime
configuration for application rollback. Do not roll back a database carrying new
cash/clinical facts. Publish only the signed, checksum-verified Windows artefact.

## Deliberate outstanding acceptance

Managers must supply/confirm pack units, batches and expiry before imported goods
are saleable, and test actual Windows USB receipt/label printers, scanner and
printer-connected cash drawer. Real national/regulatory/insurer/payment feeds
remain disabled templates pending approved endpoints and credentials. This
release does not certify those providers or physical hardware. Untracked Stage
2D.2 prototypes and certification drafts remain preserved and excluded.
