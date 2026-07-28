# TibaTrace POS Physical Validation Runbook

## Current status

Physical certification is not complete. On 2026-07-28, no Android device was
connected through ADB and the local validation host had no configured printer.
The current native POS release exercises print jobs only through the explicit
deterministic simulator; it must never be represented as hardware evidence.

## Required equipment

- A Windows POS terminal running the signed MSIX package and assigned to the
  target tenant, branch, register and operator shift.
- An Android POS device with hardware-backed keystore enabled and developer
  access for installation/log capture.
- A configured receipt printer, barcode scanner and cash drawer. Capture the
  model, connection type, driver/firmware version and configured device name.
- Test stock, a safe clinical prescription, and a non-production payment test
  plan approved by the tenant.

## Pre-flight checks

1. Record the app version, backend release, device identifier, register,
   branch, business date and authenticated operator.
2. Confirm the register session and operator shift are open and mapped to that
   device. Do not continue on an unassigned or attention-required status.
3. Confirm the printer adapter and target are configured. A `SIMULATOR`
   transport is a failed physical precondition, not a passing result.
4. Confirm the barcode scanner delivers the expected input and the cash drawer
   is connected through the approved printer/terminal path.

## Receipt and recovery protocol

1. Complete one authorised cash test payment and confirm that exactly one
   immutable receipt document and original print job exist.
2. Verify the physical receipt content against the POS snapshot: patient,
   dispensing number, medicines, quantities, tender, amount, change, register
   session and copy classification.
3. Simulate a controlled paper-out or offline printer condition. Verify that
   settlement remains confirmed, the job becomes `RETRY_REQUIRED`, and the
   failure reason is visible in Print Centre.
4. Restore the printer and retry the same job. Verify its identifier is
   unchanged and the attempt count increments once.
5. Request a reprint with a stated reason. Verify a new copy number and
   reprint reason; it must not overwrite the original document.
6. Restart each client while a non-destructive recovery test is pending.
   Verify Sync Centre requires an idempotency-key lookup and does not resend a
   payment, collection or supply automatically.

## Scanner, drawer and Android protocol

1. Scan an in-assortment barcode and confirm the tenant/branch catalogue item
   is resolved. Scan an unknown barcode and verify no item is added.
2. Verify the cash drawer opens only after the authorised cash transition and
   that a hardware failure creates an actionable device-health signal.
3. On Android, rotate/restart the app, restore the secure session, and verify
   queued consequential actions retain their original idempotency key.
4. Capture accessibility evidence on Android: TalkBack labels, focus order,
   modal focus containment and the announced blocking/error state.

## Evidence to attach

- Device and printer configuration, app/version and backend release details.
- Redacted screenshots or video for each protocol step.
- Receipt, label and reprint samples with document/copy identifiers.
- Sync Centre, device-health and backend event/audit references.
- Results signed by the accountable operator and validation reviewer.

Do not change the release decision from `POS_UI_UX_BLOCKED` until all required
evidence is reviewed and the physical transports are implemented and validated.
