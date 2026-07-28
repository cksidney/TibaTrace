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

## World-Class UI/UX Design Certification

### Information architecture

The implemented native workspaces are intentionally limited to the workflows
that exist today. Windows has a compact product header, server-derived
operational status, then either the prescription workspace or retail workspace.
The retail workspace uses three stable regions: find/scan, authoritative basket
and a sticky sale summary. Android uses a compact header and operational strip,
full-width tablet panels, contextual bottom navigation and a sticky retail
total/action region.

The repository does not yet implement complete Patients, Held, Tasks, Reports,
More, Printing or Sync Centre workspaces. They are not represented as dead
navigation controls; adding labels without server-backed screens would degrade
operational clarity.

### Shared interaction standards

- `action` tokens distinguish a teal next action from green verified state.
- `deriveRetailPrimaryAction` provides one exact primary action from the
  server-provided retail state on Windows and Android.
- Retail line mutations rehydrate the complete transaction using the POS API;
  clients do not recompute totals, discounts or taxes locally.
- Windows `F2` focuses catalogue search and `F12` focuses barcode input. These
  shortcuts only navigate or focus; they cannot complete clinical, stock or
  financial actions.
- The Windows footer navigates to payment or collection review. It never posts
  a zero-value payment or confirms collection by itself.

### Clinical and retail safety boundary

Prescription medicine dispensing remains the only native workflow with the CDS
screening integration described above. Both retail workspaces display that
prescription medicines must use the prescription workspace because retail
medicine screening is not yet implemented. This is an explicit limitation, not
a claim that all retail items are clinically irrelevant.
