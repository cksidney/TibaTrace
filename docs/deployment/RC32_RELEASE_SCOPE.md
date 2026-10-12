# TibaTrace 1.0.0-rc32 release scope

Approved on 2026-10-12: deploy validated HQ and backend changes while preserving
the unfinished Stage 2D.2 prototype locally, outside the release.

## Included

- Tenant workspace navigation and forms for clinical intake, patients,
  practitioners, medicine catalogue, insurance, inventory and GS1.
- Governed patient identifier verification and practitioner licence decisions.
- Draft medicine intake and activation of the tenant product chain.
- Sandbox insurance coverage setup and supply-derived claim drafting.
- Inventory location provisioning, stocktake and transfer workflows.
- Regulatory impact assessment, inventory-backed recall holds/releases and
  closure evidence requirements.
- Platform integration endpoint/credential-reference setup and approval states.
- Separate platform audit trail for global regulatory and integration decisions;
  tenant audit ownership remains mandatory.
- The compact mandatory password-change form from rc31.

## Database changes

Production backend baseline: `a302847d46f2be2826bfc1e12ba927ebe8afa3b3` (rc29).

- `integrations.0005_activation_request_state_choices`: expands state choices.
- `audit.0003_platformauditevent`: adds the platform operation audit table.
- `inventory.0005_recall_ledger_events`: replaces two nonzero-delta constraints
  with one constraint allowing zero deltas only for recall hold/release events.

Keep the prior application images available for runtime rollback. Do not reverse
the recall migration after zero-delta recall events have been recorded: the old
constraints cannot accept that history. Preserve the pre-deployment database
backup and use a separately approved restore plan if database recovery is needed.
No demo reseeding or real tenant transaction generation is part of deployment.

## POS and external acceptance

Windows POS source and shared contracts are unchanged since signed version 1.0.4.
Retain that installer and verify its live release metadata and download checksum.
Android signing remains unconfigured; do not manufacture a replacement key or
publish an unsigned upgrade. External integrations remain templates until approved
provider onboarding. Cash-only settlement and manager hardware/stock acceptance
limitations remain in force.

## Preserved, not shipped

- `backend/apps/platform/demo/generation/stage2d2.py`
- `backend/apps/prescription/services/dispensing_lifecycle.py`
- `backend/tests/test_demo_stage2d2_hardening.py`
- The five local `docs/demo/STAGE2D2_*.md` draft reports.

These drafts reference a missing validator, mutate lifecycle/payment state without
the real transaction services, and report certification/performance results that
have not been demonstrated. They are not production acceptance evidence. They
remain intact in the local checkout; release CI must run every test actually
present in the committed release, with no test exclusions.

Local package-manager caches, the stray pnpm lockfile and the generated Word
guide are not application runtime changes and are not deployment inputs.
