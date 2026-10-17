# rc54 and Windows POS 1.0.11 release verification

Status: deployed at https://tibatrace.esenai.co.ke/ on 16 October 2026 and reverified on 17 October 2026 (Africa/Nairobi).

Server source: `8c77e75c1fa91ffb3cb6ade9f433110b166484a1`, tag `tibatrace-v1.0.0-rc54`.
Windows source: `24a5a7749e77d361d7d0c66fca7db20cea29fe24`, tag `pos-windows-v1.0.11`.
The Windows and shared-package Git trees are identical at both sources. This report is a documentation-only follow-up; the deployed application remains the tagged rc54 source.

## Validated draft changes

- Physical register setup uses the shared intake modal. It enforces tenant/branch scope, device or identity management permission, unique register codes and non-negative KES float amounts. Refused submissions retain the draft for correction; pending submissions cannot be duplicated.
- Cash-control views, current POS shifts and new X/Z snapshots show completed retail and clinical customer visits. These are visits, rather than distinct people. Historical reports without the metric show **Not recorded**.
- Episode steps cannot change during payment or clinical writes. Existing payment recovery, clinical gates, refunds, sample-data indicators and TibaTrace branding are preserved.
- HQ National Integrations includes **KRA eTIMS VSCU** monitoring with tenant and branch scope, setup/detail modals and accepted fiscal evidence. It reads the existing payment fiscal outbox. No competing fiscal ledger, locally fabricated signature, raw provider SVG or browser credential activation is introduced.
- An explicit platform owner may prepare an unprepared invoice after existing server configuration and item/tax mapping validation. The existing worker delivers it. Queued, sending, uncertain, accepted and rejected submissions cannot be retransmitted from this screen.

The original user checkout was left unchanged. Already-deployed dashboard/workflow improvements were preserved through source review. Incomplete demo certification placeholders and a second clinical transition engine were excluded; they remain in the original checkout. No clinical or live provider certification is claimed. Dependency stores, alternate generated lockfiles and unrelated document exports were excluded.

## Validation

[Production Images run 38952369027](https://github.com/cksidney/TibaTrace/actions/runs/38952369027) passed on the exact rc54 source:

- 2,211 SQLite and 2,211 PostgreSQL 16.15 tests, with zero failures, errors or skips.
- HQ 95, Windows POS 121, Android 41 and shared-package 214 tests; application typechecks and builds passed.
- All 58 audited Python dependencies and both runtime image vulnerability scans had zero reported findings at build time.
- Release checksums, amd64 revision/version labels, SBOMs, GitHub build provenance and migration evidence passed. There are no schema changes from the accepted rc52 baseline.

The superseded rc53 candidate was not deployed. Its suite found one migration-inventory mismatch caused by an unused migration-package initializer in the API-only fiscal monitoring app. Removing that initializer resolved the mismatch; the inventory guard and test gates were retained unchanged.

[Windows run 38950061343](https://github.com/cksidney/TibaTrace/actions/runs/38950061343) passed POS tests/typecheck/build, executable and installer icon verification, Authenticode signature/timestamp, managed certificate enrollment, and installation/launch on a clean Windows runner.

Synthetic browser acceptance covered register-modal focus and labels, retained rejected drafts, corrected retry, tenant headers, uncertain fiscal outcomes without retry, setup-modal dismissal, light/dark presentation and 390/1024-pixel layouts. The retained fiscal screenshot uses synthetic data. The temporary local review directory was cleared between sessions; CI artifacts and server evidence were recovered and live checks rerun on 17 October. The original checkout remains intact.

## Immutable production images

Backend: `ghcr.io/cksidney/tibatrace-backend@sha256:dbfbbda5366546a35073076e5041f3337328bfc4051208f6bc69b02895a0c50a`

HQ: `ghcr.io/cksidney/tibatrace-hq-web@sha256:a41259a196fc9827525c9d0932f013087426caeae80378ea08ddab95fb07d8ec`

Production source directory: `/opt/tibatrace/releases/tibatrace-1.0.0-rc54-8c77e75c-20261016`; `/opt/tibatrace/current` points there. The deployment baseline is the accepted server source above.

## Signed Windows release

Windows **1.0.11 build 11** is published in the authenticated tenant POS download catalogue, release ID `8085dc5c-b231-47fc-9266-053af5c6aee2`. Install the managed package on each till to receive the updated Windows screens; server deployment does not replace installed clients.

Managed ZIP: 108,211,678 bytes, SHA-256 `c69f75ec0146873150bfcf95c93d1da0d33b54a8cbe0403ffa3c4ed3535f86f9`.

Embedded installer SHA-256: `9352ee62ac65743d2cef42b57618beb01ba692e57ddf13089cb3e1f470469af5`.

Managed public certificate SHA-256: `4c60fdc90f8bf35c2fd698ae0962adbbc015659a7cb294595195faa992affe02`, unchanged. This is managed-device distribution with certificate enrollment, not a publicly trusted installer certificate. TibaTrace executable, installer and shortcut branding passed the Windows gate.

The full authenticated HTTPS package download matched its expected size and hash, including a fresh verification on 17 October. Anonymous download was refused. Prior published installers and the minimum-supported-build policy were retained.

## Live acceptance and recovery

Fresh PostgreSQL custom backup: `/opt/tibatrace/backups/tibatrace-rc54-predeploy-20261016T194843Z`. Restore inventory/read and checksum passed before activation. The retained dump checksum was reverified on 17 October: `2c060694f26f028585c5ff420272b4edd29c2fd1bc459bf4869ae53df176c0d1`.

No schema changes or database restore were needed. Prior rc52 immutable backend/HQ images and the backup remain available for rollback. Only unused older TibaTrace images were removed after checking container references; other projects, data, backups and published installers were retained.

Fresh read-only live checks passed for API/HQ health, all four runtime source labels, public asset integrity, PostgreSQL/payment schema, tenant-manager and UUID audits, original-method refund backfill, exactly one source per payment, registered workers, and payment options across five branches. Authenticated fiscal profile/queue and register-route checks passed for both operational tenants without creating a register or submitting an invoice.

Access checks covered 21 active tenant identities and two explicit owners. Authenticated tenant navigation, owner-only API refusal, foreign-tenant header refusal and owner global/selected-tenant navigation passed. Runtime API, worker, beat and HQ had zero restarts or unexpected errors; scheduled fiscal/reconciliation tasks completed successfully.

Acceptance created no clinical, stock or financial test records and changed no credentials or grants. The installer download uses the expected download audit trail. Provider activation flags remain disabled. Acceptance files and CI artifacts are retained in `acceptance-rc54/` inside the deployed release, including `FINAL_ACCEPTANCE.json`, a checksummed archive, native public metadata and the verification report.

## External activation still pending

The installed VSCU service needs the configuration location the user will supply, registered-device details, item/tax mappings, invoice numbering baseline and live acceptance. Daraja API configuration and live validation are also pending. Neither provider is represented as operational before those requirements are met. Mobile-money refunds require a verified reversal integration. Common card terminals continue to use the external terminal's approval reference; automatic terminal integration is not claimed. Physical terminal and printer acceptance requires the customer hardware.

Payment operation and recovery instructions remain in `docs/POS_PAYMENT_WORKFLOW_GUIDE.md`.
