# TibaTrace POS UI/UX Certification Record

**Decision: `POS_UI_UX_BLOCKED`**

**Assessment date:** 2026-07-28  
**Scope:** Windows POS, Android POS, shared POS modules and the supporting
cash-control read API.

This is a release decision, not a visual review. The current native products
provide a clinically guarded dispensing workflow for existing prescription
episodes. They do not yet provide the complete pharmacy POS workflow requested
for retail selling, financial register control, printing and offline
operations. This record must not be interpreted as a production certification.

## Validation evidence

- `npm run typecheck --workspace=@dawatrace/shared` — passed.
- `npm run typecheck --workspace=@dawatrace/pos-windows` — passed.
- `npm run typecheck --workspace=@dawatrace/pos-android` — passed.
- `npm test --workspace=@dawatrace/shared` — 160 tests passed.
- `npm test --workspace=@dawatrace/pos-windows` — 92 tests passed.
- `npm test --workspace=@dawatrace/pos-android` — 38 tests passed.
- `.venv/bin/pytest -c backend/pytest.ini backend/tests/test_pos_shift_api.py -q`
  — passed.

The first backend test attempt against `/Users/sidneykibet/venv` was not used
as evidence because that virtual environment runs Django 4.2.11, while this
repository requires the Django 5.1 API. The repository `.venv` runs Django
5.1.15 and was used for the passing result above.

## 64-point readiness matrix

| # | Control | Status | Evidence / release implication |
|---:|---|---|---|
| 1 | Native POS product scope defined | Partial | Clinical dispensing is implemented; retail POS scope is not. |
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
| 13 | Printer indicator | Partial | Last health report and paper level are shown; no printer adapter exists. |
| 14 | Operational notifications | Partial | Unresolved operational context is visible; no notification centre exists. |
| 15 | Lock POS action | Absent | No workstation lock UI is implemented. |
| 16 | Register opening workflow | Blocked | No native authoritative register-open action exists. |
| 17 | Opening-float denomination count | Blocked | No native cash-declaration workflow exists. |
| 18 | Pre-sale register enforcement | Blocked | Payment/supply endpoints do not bind to RegisterSession. |
| 19 | Branch assignment enforcement | Partial | UI detects assignment; server transaction binding is absent. |
| 20 | Previous Z verification | Blocked | Native app does not consume or enforce Z closure. |
| 21 | Windows 1366×768 validation | Not validated | No full-screen visual test at mandated resolution. |
| 22 | Windows 1920×1080 validation | Not validated | No full-screen visual test at mandated resolution. |
| 23 | Android tablet layout validation | Not validated | No device or emulator validation was performed. |
| 24 | Desktop keyboard workflow | Partial | Existing keyboard helpers are tested; no full POS key map exists. |
| 25 | Barcode scanner workflow | Absent | No scanner adapter or retail barcode flow exists. |
| 26 | Retail catalogue search | Absent | Native POS has no retail sale workspace. |
| 27 | Retail basket | Absent | Native POS only opens existing dispensing episodes. |
| 28 | Branch pricing | Absent | No retail price resolution is presented in native POS. |
| 29 | Promotions and discounts | Absent | No authorised discount flow is implemented. |
| 30 | Held and resumed retail sales | Absent | No retail transaction lifecycle exists. |
| 31 | Prescription queue | Implemented | Windows and Android load server-backed dispensing queues. |
| 32 | Patient identity banner | Implemented | Resolved patient identity is displayed without invented data. |
| 33 | Allergy status | Implemented | Empty allergy data is rendered as unknown, not “none”. |
| 34 | Prescription workflow ribbon | Partial | Windows ribbon exists; Android uses staged navigation. |
| 35 | Clinical screening | Implemented | Native actions use authoritative screening output. |
| 36 | Critical clinical blockers | Implemented | Clinical and payment/supply gates surface blocking states. |
| 37 | Pharmacist review panel | Partial | Windows review components exist; end-to-end decision flow is incomplete. |
| 38 | Controlled-medicine verification | Partial | Backend/client capability exists; not a complete native workspace. |
| 39 | Insurance context | Partial | Episode data exposes cover identity; claim and preauthorisation UI is absent. |
| 40 | Per-line insurance state | Absent | Native apps do not show coverage per dispensing line. |
| 41 | FEFO allocation | Partial | Backend allocation rules exist; no native manual-selection experience exists. |
| 42 | Batch and expiry verification | Partial | Backend/client capability exists; no complete scanner-led UI. |
| 43 | Preparation workflow | Partial | Dispensing workspace shows lines; preparation scan/label actions are incomplete. |
| 44 | Independent final check | Partial | Windows components exist; separation-of-duties flow is incomplete. |
| 45 | Payment amount and status | Implemented | Server-authoritative due and settled amounts are displayed. |
| 46 | Cash payment | Implemented | Existing dispensing payment path is guarded and idempotent. |
| 47 | Card payment | Partial | Manual approval tender only; terminal integration is absent. |
| 48 | M-PESA payment | Blocked | Tender is disabled; no settlement integration exists. |
| 49 | Split tender | Blocked | Shared helper exists but backend settlement rejects split tender. |
| 50 | Unknown-payment recovery | Implemented | Durable journal and server refresh prevent unsafe retries. |
| 51 | Supply and collection separation | Implemented | Collection remains a separate idempotent server action. |
| 52 | Receipt printing | Absent | No receipt printer adapter, queue or retry UI exists. |
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
   declarations, movements, X reports, Z closure, handover and reprint flows.
4. Build retail catalogue, assortment, pricing, barcode, stock and receipt
   workflows backed by the current tenant’s authoritative APIs.
5. Implement device adapters and deterministic print/sync queues, then validate
   physical printer, drawer and scanner behaviour.
6. Run end-to-end workflow, accessibility and visual validation on the mandated
   Windows and Android device profiles.

Until those conditions are met, this code should be released only as a
controlled clinical-dispensing pilot, not as a complete pharmacy POS system.
