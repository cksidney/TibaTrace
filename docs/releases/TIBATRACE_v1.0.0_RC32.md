# TibaTrace v1.0.0-rc32 — governed HQ workflows

Full server release for HQ, API, worker and beat, replacing backend rc29 and HQ
rc31 with the same committed source revision.

Includes tenant clinical intake, patient/practitioner governance, draft medicine
authoring, sandbox insurance setup and supply-derived claim drafting, inventory
workflow forms, regulatory recall response, GS1 tools and platform integration
configuration. Retains the compact mandatory password-change screen.

Three migrations are required: the platform audit table, integration approval
state choices and the reviewed recall ledger constraint replacement. Take and validate a PostgreSQL backup before
activation. See [release scope and rollback restrictions](../deployment/RC32_RELEASE_SCOPE.md).

Windows POS 1.0.4 is unchanged and remains the matching signed installer. Android
cannot ship without the existing approved release-signing key configuration.
External integrations remain disabled/templates until provider onboarding.

By explicit operator decision, the unfinished Stage 2D.2 prototype and its claimed
certification reports are preserved locally and excluded from this release.
Release CI runs the full committed business test suite without exclusions.
