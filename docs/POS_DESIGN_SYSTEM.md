# TibaTrace POS Design System

## World-Class UI/UX Design Certification

### Foundations

`packages/shared/src/design-system/` is the platform-neutral source of truth
for spacing, radii, typography, control sizes, surfaces, text contrast, focus,
elevation, duration and semantic status palettes. Windows renders those values
as CSS values; Android maps them into React Native styles.

The `action` token set reserves teal for the next available action. Completion
and verified status retain semantic green, so a primary control never implies
that an operation is already confirmed.

### Shared vocabulary

Clinical states include `Blocking`, `Pharmacist review`, `Action required`,
`Processing`, `Safe to proceed`, `Offline` and `No longer valid`. Statuses
include a label, icon name, description, live-region priority and progression
meaning; colour is never their only signal.

Retail primary actions use the same terms on both platforms:

| Server state | Primary presentation |
|---|---|
| No sale | `Start new sale` once a store is selected |
| Draft without lines | `Add an item to continue` |
| Draft with lines | `Prepare payment` |
| Held | `Resume sale` |
| Ready for payment | `Settlement required` — disabled because settlement is not implemented |

### Current component inventory

| Responsibility | Windows | Android | Status |
|---|---|---|---|
| Operational context | `OperationalStatusBar` | `OperationalStatusStrip` | Implemented presentation |
| Patient safety | `PatientSafetyBanner`, `ClinicalRail` | `PatientBanner`, `ClinicalSummaryCard` | Implemented for prescription workflows |
| Retail transaction | `RetailWorkspace` | `RetailScreen` | Implemented foundation |
| Primary retail action | Shared `deriveRetailPrimaryAction` | Shared `deriveRetailPrimaryAction` | Implemented |
| Payment settlement | `PaymentPanel` for dispensing | `PaymentScreen` for dispensing | Retail settlement incomplete |
| Printer, Sync Centre, shift close | None | None | Blocked |

No cross-platform JSX component library is claimed. The native platforms share
semantics and tokens, not a renderer. This avoids forcing desktop tables into a
tablet workflow.
