# TibaTrace 1.0.0-rc50 — ledger-backed POS checkout

Windows POS 1.0.9 adds full and partial cash/manual-terminal card collection for
clinical and retail checkout, encrypted recovery of interrupted commands,
stock reservation before retail collection, safe completion of already-paid
sales, original-method supervised refunds/unfinished-payment voids, and accurate
cash/noncash register reconciliation. Unresolved payments block register closure.
The TibaTrace executable/installer branding from 1.0.8 is retained.

The backend adds tenant/branch-configured Daraja transport and authenticated
status polling plus an independent VSCU invoice/credit-note outbox. Credentials,
registered VSCU device/mappings and external acceptance evidence are still
required before enabling them. Mobile reversals are unavailable pending supplied
verified integration. No production test payments, provider credentials, grants
or medicine records are seeded by this release.

Migrations: pos_transactions 0004/0005; prescription 0017/0018. Existing cash
refunds are backfilled from their immutable original amount. Mixed collections
and retail ledger intents make old application code unsuitable for automatic
rollback after trading begins. Quiesce trading/workers for migration and final
acceptance; retain the verified database backup and rc49 images/source. Before
opening trading, a failed activation can restore rc49; after new financial data,
prefer a forward repair and reconcile before any database rollback.

Release requires final-source SQLite/PostgreSQL 16 CI, application gates,
image security/provenance and signed Windows install/launch/icon verification.
Deployment acceptance evidence is recorded separately after those gates pass.
See [checkout operations and configuration](../POS_PAYMENT_WORKFLOW_GUIDE.md).
