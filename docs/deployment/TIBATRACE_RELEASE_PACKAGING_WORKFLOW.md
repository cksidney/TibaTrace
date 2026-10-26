# TibaTrace server release and deployment workflow

**Current process:** GitHub Production Images workflow builds, validates and publishes immutable server images. Production activation is a separate, operator-controlled SSH deployment; the workflow does not deploy to the VPS.<br>
**Production host:** `tibatrace.esenai.co.ke` at `159.69.34.39`; release root `/opt/tibatrace`.

## 1. Prepare an exact release source

1. Set `VERSION` and add `docs/releases/TIBATRACE_v<VERSION>.md`.
2. Review the source diff and migration plan. Exclude local secrets, generated artifacts and unrelated worktree changes.
3. Confirm the repository variable `DEPLOYMENT_BASELINE_SHA` names the source commit actually running in production. The Production Images workflow inventories migrations relative to this value. Update it after each verified activation; do not guess the baseline.
4. Commit the complete source and create the matching annotated `tibatrace-v<VERSION>` tag. The tag must match `VERSION` exactly.

## 2. Build and validate in GitHub Actions

Push the annotated tag. The `Production Images` workflow is the only production image builder. It runs the exact-source SQLite and PostgreSQL business suites, frontend checks/tests/builds, migration inventory and consistency checks, runtime startup checks, dependency and container scans, SBOM generation and signed provenance. It publishes only after every gate passes.

Retrieve the `release-evidence-<VERSION>-<SHA>` artifact. Verify its `SHA256SUMS`, release manifest, OCI source/version/revision labels, image digests, migration inventory, SBOMs and GitHub attestations. Use immutable `ghcr.io/...@sha256:...` references in production, never `latest` or a mutable release tag.

If any gate fails or evidence is missing, do not deploy. Fix the source, create a new candidate commit/version/tag and rerun the full workflow; do not bypass or reuse a failed publication.

## 3. Prepare production safely

Before changing the live environment:

- Confirm the live image labels, release pointer, schema and `DEPLOYMENT_BASELINE_SHA` agree.
- Check available disk, memory, backup space and Docker image retention. Do not build images on the shared production VPS. Preserve the running and immediate rollback release/images; remove no unrelated service data or volumes.
- Create a root-only, checksummed backup of PostgreSQL, production configuration/secret references and the clinical-object volume. Verify archive integrity and restore inventory before deployment. Keep the environment backup mode `0600` and never print/copy secret values into release evidence.
- Review the candidate migration against current production. Record forward/rollback behavior. Never reverse a migration or restore an old database over newer accepted transactions without a reviewed recovery plan.
- Update the protected production secret file atomically, with a root-only backup and restrictive permissions. Provision required encryption and lookup keys before starting a release that requires them; preserve legacy keys needed by existing data and backups.
- Keep malware scanning, patient uploads, DHA/HIE, RX and checkout settings at their approved current states. Do not mark unscanned files clean or enable an integration as part of a server release without separate authorization and acceptance.

## 4. Activate the immutable release

Create a versioned release directory containing the tagged `deploy/tibatrace/` configuration, `VERSION`, release notes and verified release evidence. Set the production image variables to the published immutable digests. Run the release's composed-configuration check before migrations.

Use `deploy/tibatrace/deploy-server.sh /opt/tibatrace/secrets/.env.production` from the new release directory. The script validates Compose, runs the maintenance migration profile, and starts TibaTrace Redis, API, worker, beat and HQ. It does not create the backup; that must be completed first.

For key/data migrations requiring tenant-by-tenant review, run the documented dry run and inspect only aggregate counts before applying. Follow the release note and approved maintenance plan. Retain the old keys and release images until all required data and backups can be read with the new release and recovery has been verified.

## 5. Accept or roll back

Acceptance must record exact source, image digests, migration state, health, worker response, public HTTPS/HQ asset identity, tenant boundary/read-only checks, key configuration IDs (never values), business-data invariants, integration states and backup/recovery references. Verify that no test clinical, stock or financial writes remain.

After successful acceptance, update the production pointer and the GitHub `DEPLOYMENT_BASELINE_SHA` to the exact deployed source. Preserve the prior release and images. If acceptance fails, stop further activation and use the reviewed rollback procedure. Database migrations are not automatically reversed; follow the release-specific recovery plan.

## 6. Current capacity note

The shared VPS was recently observed with 1.4 GB free on a 38 GB root filesystem. Recheck disk and memory immediately before transfer, backup and image pull. The host has unrelated production applications; do not reclaim their images, volumes, logs or data. If required headroom is unavailable, arrange approved capacity or remove only individually verified obsolete TibaTrace artifacts while retaining the live release and rollback target.
