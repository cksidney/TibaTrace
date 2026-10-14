# rc42 candidate — asynchronous HQ workspace test synchronization (held)

Held before publication or activation. The retained rc40 real-PostgreSQL run
completed with 35 failures and four setup errors out of 2,117 tests. Beyond the
reviewer-scope audit already fixed in rc41, it exposed nullable joined-row lock
targets in retail checkout/refunds, stocktake revisions and onboarding completion;
an unsupported UUID aggregate/locked GROUP BY in B2B reservation; and a
backend-specific decimal-string assertion in the inventory-velocity test.
rc42 carries those unchanged business paths, so its workflows were canceled.
Production remains rc37; green health endpoints do not prove those workflows.

Carries the rc41 commercial pricing, six source-report and read-only maintenance
admin scope. rc41 was not published or deployed: all 2,119 SQLite backend tests
passed, but one of 68 HQ tests used a fixed delay and accessed the commercial-list
selector before its options-backed form was mounted.

The helper now waits for the actual enabled workspace with a bounded timeout,
reports a missing control explicitly, and uses the element's own value setter.
A delayed-options regression preserves the real review-only form assertions.
No test is skipped, retried automatically or relaxed to accept an absent form.
Local HQ typechecking and all 69 tests pass. All clean-checkout and exact-source
SQLite/PostgreSQL gates must still pass before image publication or activation.

Backend business code and native POS source are unchanged from rc41. Windows
remains signed managed-device 1.0.5; Android release signing, provider onboarding,
Manager stock/hardware acceptance, unsupported report packs and governed customer
agreement/promotion/profile authoring remain open. Production is still rc37.
