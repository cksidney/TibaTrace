# TibaTrace v1.0.0-rc24 — activation and honest reporting

Includes rc23's tenant/JWT, temporary-password, commercial authority, payment and
disabled national-provider onboarding hardening. rc23 was not deployed while its
new mandatory full business suite was still under validation.

## POS activation

An additive migration persists tenant/branch/register-bound activation requests.
Only actual platform administrators can independently approve/reject; requests
cannot self-approve. One-time hashed challenges expire after 15 minutes. Enrolment
issues signed, expiring credentials; validation checks durable approval, device,
fingerprint, register assignment, expiry and revocation. Active device requests
are unique at the database level. Challenges and credentials are excluded from
audit metadata.

Windows 1.0.4 and Android alpha.6 add secure credential persistence, online
startup/revalidation and automatic operational proof headers. Windows governance
no longer infers platform authority from usernames or routes rejection/revocation
through approval. Production POS mutations require approved device proof; old
clients must upgrade and enrol. Installation fingerprints are not hardware
attestation. Signed installers and physical Manager acceptance are separate gates.

## Reporting

Implemented report packs query tenant source data rather than returning one
generic snapshot under every title. Settlement collections and completed refunds
use their actual timestamps, Decimal amounts and separate currencies; collections
are explicitly not accrual revenue. Inventory and audit exports use scoped source
records. Current stock/dashboard snapshots reject historical date filters. Large
exports fail explicitly rather than silently truncating.

Unimplemented catalogue packs return 501 and are disabled in HQ. CSV neutralizes
spreadsheet formulas, XLSX is real OOXML with literal cells and compliance PDF is
a genuine PDF. Certification bundles no longer fabricate test passes, security
results, readiness percentages, framework versions or SLSA levels. External
acceptance and commit-matched CI evidence are marked unverified when unavailable.

Demo reservation planning now budgets remaining eligible stock and excludes
expired/held/recalled batches without weakening production safety guards.

This candidate is not full trading/regulatory certification. Retail checkout,
real opening-stock publication, governance reviews, installer signing/physical
tests, verified external endpoints and operational restore evidence must each be
closed with their own evidence. Do not treat planned reports as implemented.
