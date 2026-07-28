# POS UI/UX — current state audit

Baseline: `418c663` on `main`, working tree clean.

This is step 1 of the certification programme (§2, §58.1). It records what exists
today, measured against the 62-section specification, so the remaining work can
be planned against evidence rather than assumption.

**It is an audit, not a certification.** Nothing here claims a workflow is
complete. Where a workflow is absent it says so plainly.

---

## 1. What the POS surface actually is

There are **three** POS implementations, not two. This matters because the
specification addresses "Windows POS" and "Android POS" and assumes shared
composition between them.

| Surface | Stack | Shares design tokens | Status |
|---|---|---|---|
| Web POS (`backend/templates/pos/pos.html`) | Django template + vanilla JS | **No** — own stylesheet, zero references to `@dawatrace/shared` | Served at `/` and `/pos/`. Confirmed by the product owner as **the real POS** |
| Windows POS (`apps/pos-windows`) | Electron + React | Yes | Builds; renderer runs against a local backend |
| Android POS (`apps/pos-android`) | React Native | Yes | Debug APK builds (35 MB, verified) |

The web POS is the most feature-complete of the three and duplicates the purpose
of both native apps in a separate stack. Any certification programme has to
resolve that first: certifying two native apps while the real POS is a third
implementation would certify the wrong thing.

## 2. Component inventory

### Windows (`apps/pos-windows/src/components/tibatrace/`)

Present: `BatchVerification`, `ClinicalRail`, `CounsellingAndCollection`,
`EpisodeTimeline`, `FinalCheck`, `PatientSafetyBanner`, `PaymentPanel`,
`PharmacistReview`, `PrescriptionWorkspace`, `StatusBadge`, `WorkflowRibbon`,
`TaskQueue`.

State: `usePosWorkflow`, `useClinicalScreening`, `keyboard`.

### Android (`apps/pos-android/src/`)

Screens: `DispensingScreen`, `PaymentScreen`, `CounsellingScreen`.
Components: `ClinicalSummaryCard`, `TibaTraceBrand`, `liveRegion`.

### Against §45 (28 mandated shared components)

Roughly **12 of 28** exist in some form, all clinical-dispensing oriented.

Absent entirely: `PosShell`, `OperationalStatusBar`, `RegisterStatus`,
`ShiftStatus`, `ConnectivityStatus`, `PrinterStatus`, `ProductSearch`,
`BarcodeCapture`, `TransactionLine`, `InsuranceSummary`, `PriceSourceBadge`,
`BatchSelector`, `TenderSelector`, `SplitTenderEditor`, `XReportPreview`,
`ZCloseWizard`, `SyncCentre`, `PermissionGuard`, `AuditTimeline`.

## 3. Workflow coverage, measured

Counting source files (excluding tests) that reference each concept across both
native apps:

| Workflow | Files | Assessment |
|---|---|---|
| Clinical dispensing | 12 | Substantially implemented |
| Payment | 5 | Implemented for dispensing; no split tender, no card, no M-PESA state machine |
| Offline / sync | 8 | Journal and queue exist; no Sync Centre screen |
| Register | 1 | Incidental reference only |
| **Shift** | **0** | **Absent** |
| **X report** | **0** | **Absent** |
| **Z report** | **0** | **Absent** |
| **Printer** | **0** | **Absent** |
| **Barcode** | **1** | Effectively absent |
| **Retail sale / catalogue** | **0** | **Absent** |

### What this means

The native POS apps implement **one workflow**: clinical dispensing of an
existing prescription episode. They are not point-of-sale terminals in the
retail sense.

The specification's §11 (retail sale), §27 (shift and cash), §29 (printer), §32
(sync centre) describe workflows with **no implementation at all** on either
native app. `api/pos/shift/` exists on the backend and no native client calls it.

## 4. Screen inventory against §57

**Windows: 27 screens mandated.** Present in some form: Login, Prescription
Workspace, Clinical Review, Payment, Preparation, Final Check, Collection, Task
Queue — **8**. Absent: 19, including every register, cash, X/Z, print, sync,
search and retail screen.

**Android: 19 screens mandated.** Present: Login, Payment, Preparation-adjacent
dispensing, Counselling/Collection — **4**. Absent: 15.

## 5. What is genuinely working

Established by inspection and live testing during this session, not assumed:

- **Patient identity is authoritative.** The dispensing serializer resolves
  `patient_name`, `patient_number`, `patient_sex`, `patient_date_of_birth`,
  `prescription_number`, `prescriber_name`, insurance and `allergies` from real
  records. Verified against the running backend: `DEMO-DISP-8001` →
  `patient_name='Grace Kamau'`, `allergies=[]`, `insurer=None`.
- **No fabricated fallbacks remain** in the dispensing path. The demo-queue
  substitution, the hardcoded penicillin allergy tag and the fixed insurer
  defaults are gone; absent data renders as absent.
- **The clinical rail states an action**, not merely a status — "Contact the
  prescriber before supplying."
- **Status semantics are disciplined.** Red is reserved for blocking; an empty
  allergy list maps to amber UNKNOWN rather than green.
- **Offline queue behaviour is honest.** A failed queue fetch renders as a
  failure with "Do not dispense from this screen until it reloads", not as an
  empty queue.
- **Timestamps render in the pharmacy's timezone** via the shared formatter.

## 6. Known defects and risks

| Item | Severity | Note |
|---|---|---|
| Three POS implementations | **High** | The real POS shares no code with the certified apps |
| No register/shift state in native apps | **High** | §5, §6, §27 unimplementable without it; backend exists |
| No printer integration | **High** | §24, §29 blocked; no adapter of any kind |
| No retail sale workflow | **High** | §11 absent; POS cannot sell a non-prescription item |
| Browser fallback uses `MemorySessionStorage` | Medium | Reload signs the operator out; Electron persists correctly |
| Web POS has no shared tokens | Medium | Type scale and version now aligned by duplication, not sharing |
| No visual regression at mandated resolutions | Medium | Harness exists for 31 component scenarios, not 1366×768 / 1920×1080 screens |

## 7. Hardware position

No hardware validation has been performed and none is currently possible in this
environment:

- Thermal receipt printer — **not available**
- Cash drawer — **not available**
- Barcode scanner — **not available**
- Android device or emulator — **not available**
- Windows host for MSIX packaging — **not available** (Electron dev runs on macOS)

Per §54 and §60 these must be reported as **awaiting hardware validation**, not
as simulator-validated, and certainly not as validated.

## 8. Recommended disposition

Ordered by dependency, not by visibility:

1. **Decide the POS surface question.** Whether the native apps supersede the
   web POS, or the web POS is the product and the native apps are shells around
   it. Everything else depends on this answer, and doing the work in the wrong
   direction is worse than not doing it.
2. **Extract shared design tokens into CSS custom properties** the Django
   template can consume, so all three surfaces share one system rather than
   three copies that happen to agree.
3. **Register and shift entry** (§6, §27) against the existing `api/pos/shift/`.
   This is the largest missing operational block and it gates X/Z, cash and
   closure.
4. **Printer adapter and status** (§24, §29), with the queue-and-retry behaviour
   the specification requires, behind an interface that can be simulated until
   hardware exists.
5. **Retail sale workspace** (§11), including barcode capture and branch
   pricing presentation.
6. **Sync Centre** (§32) over the existing offline journal.
7. Accessibility, keyboard, visual regression and E2E (§33, §44, §51–53) once
   the screens they would cover exist.

## 9. Estimate

Steps 3–7 are each multi-day pieces of work with backend integration, tests and
documentation. The full 62-section programme — 46 screens, 28 components, 13
documents, 17 end-to-end scenarios, hardware certification on four device
classes — is a multi-month team effort.

It cannot be completed in a single session, and reporting it as complete would
be the precise failure this codebase has been repeatedly corrected for: a
confident claim with nothing behind it.
