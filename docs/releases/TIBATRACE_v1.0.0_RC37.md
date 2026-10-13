# TibaTrace v1.0.0-rc37 — business-date and installed-till integrity

Supersedes the undeployed rc36 candidate. Includes its complete reviewed workflow
scope and four migrations relative to live rc35; see RC36_WORKFLOW_CLOSURE.md and
the rc36 release notes for the implementation and acceptance register.

Full local regression discovered three midnight failures (2077 passed, 3 failed).
The candidate now uses the configured business calendar date for practitioner
licence expiry, supplier eligibility at actual receipt, procurement lead time and
delivery timing. Fixed-time Nairobi/UTC boundary tests preserve these controls.

Windows POS 1.0.5 now reads its version and explicit build number from the installed
application manifest, not an npm launch environment. Native requests send that
identity and Sync Centre checks the actual build. Inconsistent installed metadata
fails closed. Local Windows typecheck/build and 105 tests passed before release CI.

Only activate after the full final backend/application, visual and immutable-image
gates pass. Take a verified fresh database backup, retain rc35 application rollback
material, pin API/worker/beat/HQ to this candidate's CI digests, and publish only the
CI-signed Windows kit with verified hashes. No real stock, credentials, provider
certification or Android signing is inferred. The 44 source-dependent report packs
and Managers' stock/hardware acceptance remain explicitly pending.
