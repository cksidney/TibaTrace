# TibaTrace v1.0.0-rc26 — release gate contract corrections

Includes rc25's retail expiry and read-only role-listing fixes. The two remaining
rc24 suite failures were outdated test expectations: CSV now includes its UTF-8
charset, and the regulator scorecard intentionally returns no numeric score
without approved endpoint and acceptance evidence. The tests now assert those
truthful behaviors.

This candidate still requires the full migrated GitHub suite, image evidence,
database backup/restore acceptance and production smoke checks before deploy.
It does not complete retail settlement/refund/receipt/till close, initial
catalogue publication, external regulator connectivity, Android signing or
Manager hardware acceptance.
