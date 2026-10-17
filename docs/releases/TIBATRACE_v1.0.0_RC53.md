# TibaTrace 1.0.0-rc53 — POS readiness and fiscal outbox integrity

This candidate retains rc52's ledger-backed payment workflow and TibaTrace
Windows branding. HQ now exposes guarded register float and business-day controls,
shows branch/device readiness, records device sync heartbeats, and explains the
store and cashier-branch requirements when no retail store is available. A
business day cannot close until its register sessions are closed and have Z
reports. A register float cannot change while its session is active.

Retail sales and refunds now use one immutable VSCU outbox per source. The former
automatic taxation path could allocate another fiscal invoice for a sale already
in the checkout outbox; that duplicate path is removed. Queue retry filtering now
applies due-time and tenant constraints before its processing limit. eTIMS and
Daraja remain disabled until the tenant supplies validated server-side VSCU
configuration, approved item/tax mappings, and Daraja credentials. Manual card
terminals continue to use their external approval reference.

The Windows POS is version 1.0.11, build 11. It retains the branded shell and
improves payment and refund status presentation. The signed installer is produced
by the Windows release workflow after typecheck, unit tests, branding checks,
signature verification, and timestamp validation.

Local validation covers all application typechecks, builds, and unit suites;
backend lint, migration consistency, focused cash-control/payment/eTIMS tests;
and the release CI then runs the complete SQLite/PostgreSQL business suite,
clean image builds, security scans, provenance, and signed Windows packaging.
The verified immutable image digests, migration inventory, backup/restore
evidence, and live acceptance checks are recorded after those gates pass.

Trading configuration remains an operational prerequisite: activate an actual
STORE/PHARMACY/DISPENSARY inventory location on the terminal's branch, grant the
cashier that branch, reconcile REG-02's open session against the physical drawer,
record its Z report, then close the 2026-10-15 business day before opening the
current business date. No store, cash count, or Z report is fabricated by this
release.

KRA requires system-to-system VSCU integration to be developed, tested, vetted,
and certified before production invoicing. Passing local software tests does not
represent KRA certification or live invoice acceptance.
