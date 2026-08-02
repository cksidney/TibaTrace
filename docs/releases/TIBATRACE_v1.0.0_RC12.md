# TibaTrace v1.0.0-rc12

Release candidate `1.0.0-rc12` promotes the complete 2026-08-02 engineering
freeze baseline into the production-integration and hardening phase defined by
the v1.0 readiness charter. It includes every change since the deployed
`0.2.0-rc10` baseline.

## Release scope

- National integration foundations for DHA/HIE, the Health Worker Registry,
  PPB premises verification, regulatory recall ingestion and provider health.
- Tenant-scoped reliability controls, idempotency, retries, dead-letter
  handling, activation governance, notifications and certification evidence.
- Batch-level regulatory recall matching, inventory holds and traceable recall
  operations.
- Enterprise HQ workspaces for integration operations, regulation, insurance,
  GS1, platform ownership, field search and executive oversight.
- The frozen shared national-integration contracts consumed by HQ, Windows POS
  and Android POS.
- Windows POS `1.0.3` and Android POS `0.1.0-alpha.5`, rebuilt from the exact
  release commit so their shared contracts cannot drift from the server.

## Database changes

This release introduces additive migrations for:

- `integrations` provider, claim, activation and reliability records;
- `inventory_recalls` regulatory notices, matches and actions;
- `pharmacy_network` national-integration premises verification fields; and
- `notifications` regulated notification delivery records.

The release pipeline must generate the structured migration inventory, execute
the complete migration graph and refuse destructive or unreported operations.

## Deployment and rollback

Production deployment must pin the immutable backend and HQ image digests
published for `tibatrace-v1.0.0-rc12`. Before migration, take a checksum-verified
database and runtime-configuration backup. Retain the deployed `0.2.0-rc10`
release and image digests as the sole rollback generation until RC12 health,
migrations and authenticated UI acceptance are complete.

Windows and Android installers remain independently versioned and signed. Never
replace previously published POS bytes under an existing version.
