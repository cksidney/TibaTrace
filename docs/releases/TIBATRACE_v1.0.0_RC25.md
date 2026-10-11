# TibaTrace v1.0.0-rc25 — expiry and read-only role listing

This candidate contains rc24 plus two business-logic corrections:

- Retail stock availability now excludes batches whose expiry date is today or
  earlier, even when a cached balance still says `NORMAL`. The retail basket
  cannot add more units than the remaining eligible stock.
- Listing tenant roles no longer creates or reactivates `TENANT_ADMIN`. Tenant
  creation and the explicit setup command remain responsible for provisioning
  the initial administrator role.

The regression tests are included in the mandatory full migrated backend suite.
Do not deploy until the commit-matched GitHub release gate passes and immutable
image digests are available.

This release does not complete retail payment/settlement, refunds, receipts, till
close, initial catalogue publication, Manager stock verification, clinical or
commercial independent review, Android signing, or physical till acceptance.
Those workflows remain unavailable or require separate documented evidence.
