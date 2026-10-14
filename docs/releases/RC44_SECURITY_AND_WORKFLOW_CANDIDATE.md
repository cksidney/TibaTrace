# rc44 — security and PostgreSQL workflow candidate

Not yet deployed. Includes the held commercial price-list maker/checker, six
source-report, read-only maintenance-admin and responsive HQ scope; PostgreSQL
checkout/refund/stocktake/onboarding/B2B reservation repairs; and the publisher-
supported dependency/runtime repairs in [the security record](RELEASE_SECURITY_GATE_REPAIR.md).
Production remains rc37 until exact-source release gates and activation pass.

## Evidence already obtained

- All 99 affected workflow tests passed on local PostgreSQL and SQLite before
  framework upgrades. All 168 affected-workflow/governance tests then passed
  on PostgreSQL with Django 5.2.18, DRF 3.18.3 and cryptography 50.0.2.
- Four new request-boundary tests and 12 fail-closed scanner-evidence tests pass.
- Full resolved Python dependency audit with pinned urllib3 2.8.0 reports no
  known vulnerabilities; no advisory allowlist or automatic fix/skip is used.
- Non-publishing [preflight 38522458153](https://github.com/cksidney/TibaTrace/actions/runs/38522458153)
  built both minimal amd64 runtime images and passed their real high/critical
  vulnerability gate with source-linked inventories. Its migration-smoke helper
  needed a persistent disposable SQLite path rather than a new memory database
  per command; corrected here. Full final-source gates remain mandatory.
- Full regression must run on PostgreSQL **16**, the verified live server major.
  The database is not upgraded by this application release. Prior 18 results are
  recorded accurately as separate environments, not parity certification.

No additional model migration beyond reviewed sales 0005. Native source is
unchanged from signed Windows 1.0.5; no new native installer is implied. Android
remains unpublished pending approved signing. The user confirmed the XP-470B
label printer; [physical acceptance](XP470B_WINDOWS_LABEL_ACCEPTANCE.md) still
needs actual media dimensions and a separately identified receipt printer/drawer.

Customer agreement/promotion/profile authoring, 38 unsupported report packs,
provider onboarding, Manager real-stock/hardware acceptance and VPS capacity
remain open. No live stock/sale/prescription/credential/access grant was created
to manufacture a passing test, and prototype drafts remain excluded.
