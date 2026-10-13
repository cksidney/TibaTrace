# TibaTrace v1.0.0-rc35 — first-login password changes

Platform administrators without a pharmacy assignment can now complete the
mandatory password change on the “Secure your account” screen. Their changes
write to the platform audit trail; users with a pharmacy assignment continue
to write to that pharmacy's audit trail. The browser session rotates only after
the audit succeeds, keeping failed changes retryable with the current password.

The form displays field validation and password policy messages returned by the
API so users can correct a rejected password.

Regression checks cover first-login changes for tenant users and platform
administrators, CSRF protection, password policy refusals, audit rollback,
session continuity, and revocation of other sessions. Local validation passed
59 focused backend tests, all 61 HQ tests, HQ typechecking/build, and changed
backend-file lint. Release CI must pass its full migrated suite and image gates
before activation.

This release introduces no database migrations relative to deployed rc33.
Deploy API, worker, beat, and HQ from the same committed revision, using the
CI-published image digests. Retain the rc33 images, release directory, and
runtime configuration for application rollback. No tenant credentials or
clinical data are changed as part of deployment. Local Stage 2D.2 drafts are
excluded from the release.
