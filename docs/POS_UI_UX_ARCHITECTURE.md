# POS UI/UX Architecture

## Clinical Decision Support and Drug Interaction Banner

The POS clinical-safety flow is intentionally server-authoritative:

1. A Windows or Android client maps the selected dispensing episode to the CDS
   request contract: patient, prescription, episode, supplied/prescribed SKU,
   quantity and dose instructions.
2. `PosClinicalBasketLineSerializer` normalises native `sku_id` and legacy
   `commercial_sku_id` into the server contract.
3. `PosTransactionContextBuilder` resolves medicine identity and clinical
   ingredients before `PosClinicalScreeningService` evaluates the rule set.
4. Persisted `PosClinicalScreening`, `PosClinicalFinding`,
   `PosClinicalDecision`, `PosClinicalOverride` and `PosClinicalAuditEvent`
   provide the clinical record.
5. The client renders returned status and findings in the active transaction
   context; server transition gates retain responsibility for blocking.

## Component ownership

| Platform | Components | Responsibility |
|---|---|---|
| Windows | `PatientSafetyBanner`, `ClinicalRail`, `PharmacistReview`, `StatusBadge` | Persistent patient and clinical context; finding visibility and review presentation |
| Android | `ClinicalSummaryCard` | Compact returned-screening status in dispensing and payment |
| Backend | CDS models, services and POS API | Rules, findings, authority, audit, offline package validation and gates |

No shared frontend module is a clinical rules engine. UI state is a rendering
cache of backend output and cannot create an approval or clear a blocker.

## Current limits

The architecture has not yet been completed for the native pharmacist review
and override workflow, Android detailed findings drawer, all re-screening
triggers, retail medicine screening, lifecycle restoration or full device
validation. Those omissions keep `POS_UI_UX_BLOCKED` in force.
