# rc52 and Windows POS 1.0.10 release verification — 16 October 2026

Status: deployed and verified at https://tibatrace.esenai.co.ke/.

Server source: `e9cac5dd1ed7149594734fcbc5e8bb1a45811f93` (`tibatrace-v1.0.0-rc52`).
Windows source: `ae0afd0d2291fa84f2cf025f430b75a548a2a962` (`pos-windows-v1.0.10`).

## Payment behaviour

Clinical and retail checkout share the authoritative payment ledger. Cash and external-terminal card payments support full and part collection with exact change, remaining balance, duplicate-reference controls and original-command recovery. Clinical, operator, branch, device, register and shift gates remain enforced. Retail reserves stock before collection, freezes the basket during payment, and issues stock and its receipt only after full settlement. If stock completion fails after collection, the recorded payment remains recoverable through Finish paid sale.

Retail refunds and unfinished-payment voids require an independent supervisor and preserve the original payment method. Returned goods remain in quarantine. Register cash reports count actual cash and block closure for unresolved payments. Offline cash is staged for recovery; staging does not confirm settlement or permit stock issue.

Daraja uses authenticated provider queries; callback acknowledgement alone never settles money. VSCU uses a durable invoice/credit-note outbox with explicit item/tax mappings and separate accepted fiscal evidence and print states. Unknown provider outcomes require reconciliation. Zero balance alone does not show Payment settled. Manual card terminals use an approval reference from the external terminal; no automatic card-terminal protocol is claimed.

## Mandatory validation

[Production Images run 38886061853](https://github.com/cksidney/TibaTrace/actions/runs/38886061853) passed on the exact server source:

- 2,188 SQLite and 2,188 PostgreSQL 16.15 tests, with zero failures, errors or skips.
- Application typechecks, tests and builds; tenant-manager and UUID-scope audits.
- All 58 Python dependencies without audit findings; both runtime image scans without findings.
- Release checksums, amd64 revision/version labels, SBOMs, GitHub provenance and the four-migration inventory verified. The exact cash-only constraint replacement was reviewed; migration gates remain enforced.

[Windows run 38892640839](https://github.com/cksidney/TibaTrace/actions/runs/38892640839) passed: 121 POS tests, typecheck/build, executable/installer logo checks, Authenticode signature/timestamp and clean Windows installation/launch. The managed certificate fingerprint remains unchanged. Local synthetic browser acceptance covered cash change, split payment, missing card approval, disabled unconfigured providers and desktop/narrow layouts. No live trading or clinical test records were created.

## Immutable production images

`ghcr.io/cksidney/tibatrace-backend@sha256:bc373f53ace389d161166a27b0aa62955b1593e1e0e7aa8a83e05159e80349d3`

`ghcr.io/cksidney/tibatrace-hq-web@sha256:9e51efaac4069b6e6ac521fd722207b0dfceb9046d22df527e3dec3d7dab35ae`

## Signed package

Install the signed managed Windows **1.0.10 build 10** on each till. Server deployment does not update installed Windows clients. Existing TibaTrace executable, installer and shortcut branding remains present.

Managed ZIP: 108,211,574 bytes, SHA-256 `4ad3d817ab8ff1a8542d5d3bec8f5795d48aaba7528e0ea2df198ccca134943e`.

Installer SHA-256: `f0c2754ac1931976bb7f1faae0bf60c7db4b690eab0b70c04255eef53f1c72db`.

## External activation still pending

The user confirmed that VSCU is installed and will provide the configuration location. Activation requires the registered device details, item/tax mappings, invoice numbering baseline and acceptance verification. Daraja API configuration and live validation are also pending. Both integrations remain disabled until those requirements are met. Mobile-money refunds remain unavailable pending a verified reversal integration. Insurance/zero-payable coverage and exemption decisions follow their separate governed workflow. Physical printer and terminal acceptance requires customer hardware.

## Live deployment acceptance

Fresh PostgreSQL custom backup and verified restore inventory/checksum: `/opt/tibatrace/backups/tibatrace-rc52-predeploy-20261016T112419Z`. All four migrations applied successfully. Prior rc49 source/images and existing installers remain available. No database restore was needed.

API/HQ health, all runtime revision labels, Django checks, schema, tenant manager/UUID audits, refund backfill and worker ping passed. Five branches were checked for payment-method availability. Actual access checks covered 21 active tenant identities and two owners, authenticated tenant/owner navigation, owner-only API refusal and foreign tenant-header refusal. Public served assets matched the running image. API, worker, beat and HQ had zero restarts or unexpected errors; both scheduled checkout tasks completed successfully.

Published catalogue ID `2b42f0df-2906-417a-8b2d-abf4167719c2`. Authenticated HTTPS catalogue and full streamed installer download matched the verified byte count and hash; anonymous download was refused. Prior 1.0.8/1.0.7/1.0.5 releases remain published, minimum supported build remains 0. Only expected release/download audit entries were created; no clinical, financial, stock, credential or grant test records were added.

Acceptance evidence: `FINAL_ACCEPTANCE.json`, CI artifacts/provenance, migration/backup record, native manifest and local UI evidence, retained in the deployed release's acceptance archive. Payment operating instructions and configuration requirements are in `docs/POS_PAYMENT_WORKFLOW_GUIDE.md`. Each till needs the managed 1.0.10 installer to receive the payment screens.
