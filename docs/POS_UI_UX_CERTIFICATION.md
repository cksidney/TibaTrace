# TibaTrace POS UI/UX Certification Record

**Decision: `POS_UI_UX_BLOCKED`**

**Assessment date:** 2026-07-28  
**Scope:** Windows POS, Android POS, shared POS modules, controlled register
operations and the retail transaction foundation.

This is a release decision, not a visual review. The current native products
provide a clinically guarded dispensing workflow, a first native server-backed
retail basket, and a durable simulator-scoped receipt queue. They do not yet
provide the complete pharmacy POS workflow requested for financial register
control, physical printing, Sync Centre and offline operations. This record
must not be interpreted as a production certification.

## Validation evidence

- `npm run typecheck --workspace=@dawatrace/shared` — passed.
- `npm run typecheck --workspace=@dawatrace/pos-windows` — passed.
- `npm run typecheck --workspace=@dawatrace/pos-android` — passed.
- `npm test --workspace=@dawatrace/shared` — 163 tests passed.
- `npm test --workspace=@dawatrace/pos-windows` — 92 tests passed.
- `npm test --workspace=@dawatrace/pos-android` — 38 tests passed.
- `.venv/bin/pytest -c backend/pytest.ini backend/tests/test_pos_shift_api.py -q`
  — passed.
- `.venv/bin/pytest -c backend/pytest.ini backend/tests/test_pos_retail_transactions.py backend/tests/test_pos_shift_api.py backend/tests/test_pos_dispensing_controls.py -q`
  — passed.
- `.venv/bin/pytest -c backend/pytest.ini backend/tests/test_pos_clinical_screening.py backend/tests/test_pos_clinical_authority.py backend/tests/test_pos_offline_package_signing.py backend/tests/test_pos_offline_dispensing.py -q`
  — passed.
- `npm run build --workspace=@dawatrace/pos-windows` — passed.
- `npm run build --workspace=@dawatrace/pos-android` — passed.
- `npm run visual --workspace=@dawatrace/pos-windows` — local structural
  checks pass at `1280×900` and `1024×768`; CI-only pixel baselines are skipped
  locally and remain awaiting review.
- `./.venv/bin/pytest -c backend/pytest.ini --no-migrations`
  `backend/tests/test_pos_enterprise_dispensing.py::test_payment_orchestration_refuses_mpesa_reference_without_provider_confirmation`
  `backend/tests/test_pos_dispensing_controls.py::test_replayed_payment_does_not_charge_twice`
  `backend/tests/test_pos_dispensing_controls.py::test_payment_is_refused_without_authoritative_pricing`
  `backend/tests/test_pos_payment_ledger.py -q` — **30 passed** (2026-07-28).
- `./.venv/bin/pytest -c backend/pytest.ini --no-migrations`
  `backend/tests/test_pos_clinical_screening.py`
  `backend/tests/test_pos_clinical_authority.py`
  `backend/tests/test_pos_enterprise_dispensing.py`
  `backend/tests/test_pos_dispensing_controls.py -q` — **92 passed**
  (2026-07-28).
- `./.venv/bin/pytest -c backend/pytest.ini --no-migrations`
  `backend/tests/test_pos_printing.py`
  `backend/tests/test_pos_dispensing_controls.py`
  `backend/tests/test_pos_label_reprint.py -q` — **36 passed** (2026-07-28).
- `./.venv/bin/python backend/manage.py makemigrations --check --dry-run` and
  `./.venv/bin/python backend/manage.py check` — passed (2026-07-28).

The first backend test attempt against `/Users/sidneykibet/venv` was not used
as evidence because that virtual environment runs Django 4.2.11, while this
repository requires the Django 5.1 API. The repository `.venv` runs Django
5.1.15 and was used for the passing result above.

## 64-point readiness matrix

| # | Control | Status | Evidence / release implication |
|---:|---|---|---|
| 1 | Native POS product scope defined | Partial | Clinical dispensing, an initial native retail basket and simulator-scoped receipt queue are implemented; register controls, physical print and Sync Centre remain. |
| 2 | Shared design tokens | Implemented | Shared tokens are used by Windows and Android. |
| 3 | Windows authenticated session | Implemented | Secure Electron session and sign-out flow exist. |
| 4 | Android authenticated session | Implemented | Keystore-backed session is required. |
| 5 | Persistent tenant context | Partial | Tenant session exists; no tenant display name is supplied to native clients. |
| 6 | Persistent branch context | Implemented | Shown when a device matches a configured register. |
| 7 | Persistent register context | Implemented | Explicit device-to-register match only; no guessing. |
| 8 | Persistent operator context | Implemented | Stable operator UUID matches the active shift. |
| 9 | Persistent shift context | Implemented | Read-only active-shift status is shown. |
| 10 | Persistent business-date context | Implemented | Read from the authoritative business-day API. |
| 11 | Connectivity indicator | Partial | API failure is shown; no device network telemetry adapter exists. |
| 12 | Sync indicator | Partial | Latest recorded register synchronisation is shown; no Sync Centre exists. |
| 13 | Printer indicator | Partial | Native Print Centre shows a durable per-device/branch queue; device health and physical transport adapters remain absent. |
| 14 | Operational notifications | Partial | Unresolved operational context is visible; no notification centre exists. |
| 15 | Lock POS action | Absent | No workstation lock UI is implemented. |
| 16 | Register opening workflow | Blocked | No native authoritative register-open action exists. |
| 17 | Opening-float denomination count | Blocked | No native cash-declaration workflow exists. |
| 18 | Pre-sale register enforcement | Partial | New retail and clinical payment service actions resolve device, register, session, shift and business day server-side; legacy operational paths remain to be migrated. |
| 19 | Branch assignment enforcement | Implemented | Retail and clinical payment actions reject tenant, branch, device and session mismatches on the server. |
| 20 | Previous Z verification | Blocked | Native app does not consume or enforce Z closure. |
| 21 | Windows 1366×768 validation | Not validated | No full-screen visual test at mandated resolution. |
| 22 | Windows 1920×1080 validation | Not validated | No full-screen visual test at mandated resolution. |
| 23 | Android tablet layout validation | Not validated | No device or emulator validation was performed. |
| 24 | Desktop keyboard workflow | Partial | Existing keyboard helpers are tested; no full POS key map exists. |
| 25 | Barcode scanner workflow | Partial | Windows and Android accept scan input and resolve active tenant barcode mappings; physical scanner validation remains outstanding. |
| 26 | Retail catalogue search | Implemented | Native clients use a server filter for tenant, branch assortment, sellable status, price and inventory eligibility. |
| 27 | Retail basket | Implemented | POS transaction and line aggregates hold immutable operational context and are used by both native clients. |
| 28 | Branch pricing | Implemented | Each retail line resolves and records an authoritative price trace before it enters the basket. |
| 29 | Promotions and discounts | Absent | No authorised discount flow is implemented. |
| 30 | Held and resumed retail sales | Partial | Native hold/resume controls and service transitions exist; controlled reassignment and restart recovery remain. |
| 31 | Prescription queue | Implemented | Windows and Android load server-backed dispensing queues. |
| 32 | Patient identity banner | Implemented | Resolved patient identity is displayed without invented data. |
| 33 | Allergy status | Implemented | Empty allergy data is rendered as unknown, not “none”. |
| 34 | Prescription workflow ribbon | Partial | Windows ribbon exists; Android uses staged navigation. |
| 35 | Clinical screening | Implemented for prescription dispensing | Native actions submit actual episode identifiers under the server-recognised `sku_id` contract; the backend resolves clinical ingredients and returns authoritative output. Retail screening remains incomplete. |
| 36 | Critical clinical blockers | Implemented for authoritative POS progression | The server rebuilds the persisted dispensing basket and rejects payment, supply and transitions to payment/supply without a current, safe CDS result. |
| 37 | Pharmacist review panel | Implemented for prescription dispensing | Windows and Android provide native decision history and a governed, time-bound override request/review/approval/revocation lifecycle with separation of duties. |
| 38 | Controlled-medicine verification | Partial | Backend/client capability exists; not a complete native workspace. |
| 39 | Insurance context | Partial | Episode data exposes cover identity; claim and preauthorisation UI is absent. |
| 40 | Per-line insurance state | Absent | Native apps do not show coverage per dispensing line. |
| 41 | FEFO allocation | Partial | Backend allocation rules exist; no native manual-selection experience exists. |
| 42 | Batch and expiry verification | Partial | Backend/client capability exists; no complete scanner-led UI. |
| 43 | Preparation workflow | Partial | Dispensing workspace shows lines; preparation scan/label actions are incomplete. |
| 44 | Independent final check | Partial | Windows components exist; separation-of-duties flow is incomplete. |
| 45 | Payment amount and status | Implemented | Server-authoritative due and settled amounts are displayed; Android payment retains the current clinical summary. |
| 46 | Cash payment | Implemented | Existing dispensing payment path is guarded and idempotent. |
| 47 | Card payment | Partial | Manual approval tender only; terminal integration is absent. |
| 48 | M-PESA payment | Blocked | Tender is disabled; no settlement integration exists. |
| 49 | Split tender | Blocked | Shared helper exists but backend settlement rejects split tender. |
| 50 | Unknown-payment recovery | Implemented | Durable journal and server refresh prevent unsafe retries. |
| 51 | Supply and collection separation | Implemented | Collection remains a separate idempotent server action. |
| 52 | Receipt printing | Partial | Settlement creates one immutable receipt snapshot and branch/device queue job. Windows and Android provide retry, cancellation and permissioned reprint in deterministic simulator mode; no physical adapter is certified. |
| 53 | Label printing | Absent | No label printer adapter or reprint workflow exists. |
| 54 | X report access | Absent | Native POS does not expose interim reports. |
| 55 | Z close and reconciliation | Blocked | Authoritative service exists, but no native controlled close flow exists. |
| 56 | Cash movement workflow | Absent | Native POS does not expose cash in/out controls. |
| 57 | Shift handover | Absent | Native POS does not expose handover controls. |
| 58 | Audit timeline | Partial | Backend events exist; no complete native audit timeline exists. |
| 59 | Offline action durability | Implemented | Secure durable action journal is tested on both native clients. |
| 60 | Safe offline dispensing | Blocked | Offline mode cannot authoritatively resolve clinical/cash-control state. |
| 61 | Sync conflict resolution | Absent | No Sync Centre or conflict-resolution workflow exists. |
| 62 | Role-aware navigation | Partial | Server capability checks protect actions; native navigation is not role-complete. |
| 63 | Accessibility validation | Partial | Component-level accessibility labels exist; full screen-reader and contrast validation is outstanding. |
| 64 | Physical hardware certification | Not validated | Printer, cash drawer, scanner, Android device and Windows/MSIX host unavailable. |

## Required closure conditions

Full production certification requires all of the following:

1. Select one supported POS product surface and retire or integrate the
   duplicate web implementation.
2. Bind every financial/dispensing transaction to an authoritative open
   `RegisterSession` and accountable `OperatorShift` on the server.
3. Implement, test and permission-protect native register opening, cash
   declarations, movements, X reports, Z closure and handover flows.
4. Build retail catalogue, assortment, pricing, barcode and stock
   workflows backed by the current tenant’s authoritative APIs.
5. Implement physical device adapters and the Sync Centre, then validate
   printer, drawer and scanner behaviour.
6. Run end-to-end workflow, accessibility and visual validation on the mandated
   Windows and Android device profiles.
7. Complete retail-medicine screening, remaining clinical invalidation
   scenarios, and restart/resume restoration of clinical decision and override
   state.

Until those conditions are met, this code should be released only as a
controlled clinical-dispensing pilot, not as a complete pharmacy POS system.

## Settlement runtime closure increment (2026-07-28)

The legacy native dispensing payment command no longer directly changes an
episode's payment state. Cash and manual card commands now create an
idempotent payment intent, tender and immutable settlement, bind the tender to
the server-resolved register session and operator shift, and project the
episode payment state from the ledger. The compatibility mirror is updated only
after that projection confirms full settlement. Episode refreshes retain the
latest settled intent so confirmed due, settled and remaining values do not
disappear after payment.

The native M-PESA and split-tender affordances remain disabled. M-PESA requires
provider-confirmed settlement and recovery, while split tender requires the
native authoritative allocation editor. Android now requires a manual card
approval reference before it can submit a card payment. This closes a direct
mutation path; it does not close the remaining payment, printing, Sync Centre,
clinical, visual or hardware requirements. The decision remains exactly
`POS_UI_UX_BLOCKED`.

## Clinical Decision Support and Drug Interaction Banner

Windows retains `PatientSafetyBanner` and `ClinicalRail`; Android retains
`ClinicalSummaryCard` in both dispensing and payment. The clients render the
authoritative screening result returned by the CDS API, not a locally calculated
interaction result. The request contract preserves `sku_id` (and accepts the
legacy `commercial_sku_id` alias) so the server can resolve the supplied
medicine before evaluating rules.

This resolves a critical data-integrity defect in the client/server boundary and
keeps clinical state visible when the Android operator enters payment. It does
**not** certify the whole clinical workflow: retail medicine screening, all
invalidation triggers and full restoration across every lifecycle transition
still require implementation and evidence. Therefore the decision at the top
of this record remains exactly `POS_UI_UX_BLOCKED`.

## Clinical Review and Progression Gate Increment (2026-07-28)

Windows and Android now open a full native pharmacist-review workspace from
the CDS finding, rather than attempting review in a small modal. Both present
the same canonical decision choices, require a clinical rationale, require
conditions for a conditional approval, show immutable decision history, and
submit only to the authenticated CDS endpoint. A conditional approval does not
release supply: the finding remains open until the stated conditions are met
and a fresh screening succeeds.

The server records the tenant, branch reference, patient and prescription
references, transaction, register, rule version, authenticated pharmacist,
rationale, conditions and follow-up actions with each decision. It replays a
matching idempotency key safely and refuses it for a different decision.

Payment settlement, transition to `READY_FOR_PAYMENT` or `READY_FOR_SUPPLY`,
and final medicine supply each rebuild the persisted dispensing basket and
require a completed, current and safe CDS screening for the exact context.
This makes a changed medicine, patient, prescription or quantity fail closed.
Quantity hashing is canonicalised, so `30` and `30.0000` represent the same
clinical context across native clients and persisted dispensing lines.

This pass is extended by the governed override and durable print increment
below. Sync Centre, restart evidence, visual certification and hardware
certification remain outstanding. The decision remains exactly
`POS_UI_UX_BLOCKED`.

## Governed Override and Durable Print Increment (2026-07-28)

Clinical overrides are no longer a direct pharmacist decision. A requester
submits a time-bound, context-hashed override request, a different authorised
operator starts and approves or rejects the review, and the backend records
conditions, expiry, revocation and controlled consumption. Conditions keep the
finding open; expiry and revocation reopen the clinical gate. Windows and
Android expose only these native modal actions and refresh the authoritative
screening result after each action.

After an authoritative settlement, the backend creates exactly one immutable
receipt snapshot and one original print job. Print transport failure cannot
reverse settlement. Jobs are held in an accountable tenant/branch/device queue
and progress through `QUEUED`, `RENDERED`, `SENDING`, `PRINTED`,
`RETRY_REQUIRED`, `FAILED` or `CANCELLED`. Retrying preserves the existing job;
a reprint creates a separately numbered copy with a required reason.

The Windows and Android Print Centres exercise those controls only through an
explicit deterministic simulator. They visibly state that no physical spooler,
ESC/POS, Bluetooth or network printer was used. The new tests provide service
and queue evidence, not physical-print certification. Sync Centre, restart
recovery, visual/accessibility evidence and hardware evidence remain required.
The decision remains exactly `POS_UI_UX_BLOCKED`.

## World-Class UI/UX Design Certification

### Verified design pass

- **One primary action:** shared retail state presentation gives Windows and
  Android the same precise next action. A prepared retail basket states that
  settlement is unavailable in the pilot; it does not present a local success.
- **Authoritative totals:** after retail add, scan, quantity or removal actions,
  both clients reload the transaction from the POS API. They no longer recreate
  subtotal, discount, tax or total values in component state.
- **Operational layout:** Windows retail has a stable find/scan, basket and
  sticky summary composition. Android has full-width touch panels and a sticky
  total/action bar. Both expose clear empty, error and safety states.
- **Safety:** the Windows footer now only opens payment/collection review; it
  cannot submit a zero-value payment. Both retail surfaces state that
  prescription medicines must remain in the CDS-enabled prescription workflow.
- **Keyboard and touch:** Windows maps `F2` to product search and `F12` to
  barcode focus. Android quantity controls and primary actions use 48dp
  minimum touch targets and labelled accessibility roles.

### Anti-pattern findings fixed

| Finding | Resolution |
|---|---|
| Client-recalculated retail totals | Server rehydration after each retail line mutation |
| Two competing footer actions with direct zero-value payment | One navigation-only primary action |
| Generic retail progression label | State-specific `Start new sale`, `Resume sale`, `Prepare payment` or explicit settlement limitation |
| Desktop-style tablet line density | Structured Android transaction rows and sticky action/totals region |
| Unclear retail medicine clinical boundary | Persistent instruction to use the prescription workspace |

### Evidence still required

This is not a full world-class design certification. Retail medicine screening,
physical printing, Sync Centre, responsive device validation, an end-to-end
visual suite for the required screens, screen-reader validation and physical
hardware evidence remain outstanding. The release decision remains exactly
`POS_UI_UX_BLOCKED`.
