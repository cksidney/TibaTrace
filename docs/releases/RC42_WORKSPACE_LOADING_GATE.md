# rc42 candidate — asynchronous HQ workspace test synchronization

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
