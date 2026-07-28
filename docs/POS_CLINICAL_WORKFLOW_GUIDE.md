# POS Clinical Workflow Guide

## Clinical Decision Support and Drug Interaction Banner

TibaTrace uses the CDS backend as the clinical authority. POS clients submit a
patient, prescription or dispensing-episode context and the supplied medicine
identifiers, quantities and dose instructions. The backend resolves the
medicine, evaluates the configured clinical rules and persists the resulting
screening, findings, decisions, overrides and audit events.

Clients must never calculate or dismiss clinical authority locally. A missing
or unresolved blocker remains a server-enforced reason not to proceed.

## Current user experience

- **Windows:** `PatientSafetyBanner` and `ClinicalRail` retain patient context,
  severity and required action within the prescription workspace.
- **Android dispensing:** `ClinicalSummaryCard` presents the returned clinical
  summary.
- **Android payment:** the same compact summary remains visible above payment
  controls, so payment focus does not obscure the clinical state.

`sku_id` is the POS request field for a supplied or prescribed SKU.
`commercial_sku_id` is supported as a legacy input alias. Clients do not send a
placeholder medicine name when identity is unknown; the server must resolve
identity or fail safely.

## Blocking and review

The CDS service determines whether a screen is safe to proceed and returns
findings and a required action. Existing guarded payment and supply transitions
must use that server result. A cashier must not use an “ignore” or “continue
anyway” action.

Windows and Android present the same native pharmacist-review workspace and
immutable decision history. A scoped override is a governed lifecycle, not a
direct bypass: an authorised requester records the rationale and a different
authorised reviewer starts and approves or rejects it against the current
screening hash. The server records expiry, conditions, revocation and the
controlled event that consumes an approval. Conditions, expiry or revocation
leave or return the finding to a blocked state. Clients must never offer an
ignore or continue-anyway action.

## Offline use

Only the signed, scope-checked offline clinical package may provide offline
clinical authority. The client must surface package expiry or invalid authority
as a reconnect-required condition. Offline result handling is not equivalent to
current online screening without valid package evidence.

## Release status

Prescription-dispensing review and the governed override lifecycle are
implemented, but this is not a complete clinical workflow certification. Retail
medicine screening, all invalidation paths and restart/resume evidence remain
outstanding. See `docs/POS_UI_UX_CERTIFICATION.md` for the current blocked
release decision and remaining evidence requirements.
