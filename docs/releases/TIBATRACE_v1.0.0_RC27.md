# TibaTrace v1.0.0-rc27 — full-gate assertion fixes

Corrects two remaining release-suite assertions without weakening the behavior
checks: role listing is compared with the tenant's pre-existing role records
and must not mutate them or create `TENANT_ADMIN`; CSV content is decoded as
UTF-8 before its title is asserted. The rc26 run had 1,892 passes and only
these two failures. No image was published from that failed run.

This candidate still requires a green full migrated suite, immutable image
provenance, database backup/restore acceptance and production smoke checks
before deployment. It does not complete retail settlement/refund/receipt/till
close, initial catalogue publication, external regulator connectivity, Android
signing or Manager hardware acceptance.
