# TibaTrace v1.0.0-rc30 — HQ password-change screen hotfix

This is a targeted HQ UI deployment. The required first-password-change screen
now has its own accessible light card, readable text/labels, stacked full-width
password inputs, a visible minimum-length hint, clear error feedback, and
responsive action buttons. It no longer inherits white text from the dark auth
page or relies on an unstyled inline form.

The component preserves the existing CSRF-protected password-change endpoint,
masked password inputs, mandatory password-change guard and sign-out callback.
Controls are disabled while updating, and repeated submissions are ignored.
Regression tests use synthetic values and mocked requests; no live credentials
are entered or changed during QA.

Only HQ is promoted for this hotfix. The API/worker/beat remain on verified rc29,
Windows POS remains 1.0.4, and Android remains deferred pending release signing.
There are no backend business-code changes or new database migrations. All
previously documented cash-only and production-acceptance limitations remain.
