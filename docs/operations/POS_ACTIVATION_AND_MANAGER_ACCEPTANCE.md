# POS activation and Manager acceptance

This checklist is operational acceptance, not a claim of regulatory certification.

## Independent activation workflow

1. A tenant Manager with `identity.manage` or tenant activation permissions creates
   an existing register in the correct branch and submits the real installation's
   device ID, stable fingerprint, register code and business justification.
2. A different platform administrator reviews the request. Tenant role names and
   usernames do not grant platform authority. Approval and rejection require a
   rationale; a requester cannot review their own request.
3. Approval returns a challenge once, valid for 15 minutes. Transfer it directly
   to the requesting Manager. It is not a reusable activation credential.
4. Enrolment must supply the approved device ID and fingerprint. It consumes the
   challenge, binds the register and returns a signed, expiring credential.
5. `/api/v1/tenant/pos-activations/requests/validate/` checks the signed credential
   against durable approval, tenant/device/fingerprint, current register assignment,
   expiry and revocation. Client-side status alone is not approval.

Requests, reviews, enrolment and revocation are audited without recording secrets.
Do not place signed credentials or challenge codes in logs, tickets or this chat.

Both native apps validate startup online and retain credentials in OS-encrypted
storage (Windows safeStorage / Android Keystore). They re-check activation every
minute. Production mutations under dispensing, payments, retail and clinical
screening require the credential; server revocation takes effect immediately.
Demo tenants and explicit development/test settings remain separate from this
production gate. Already-installed older clients must upgrade and enrol before
using these production mutation paths. Physical native acceptance remains pending.

## Manager-owned acceptance

- Confirm TransElgon's actual sale/stock units, pack conversion factors, prices,
  batches and expiry dates. Unconfirmed source lines must remain non-saleable.
- Confirm the superintendent's and dispensing practitioners' valid licences.
  Internal/manual verification is not a national-registry lookup.
- Install the Windows and Android builds matching the approved release manifest.
  Test scanner input, receipt/label printers, cash drawer and offline reconciliation
  on each real till; record device, build, outcome and responsible Manager.
- Test activation, incorrect/expired/reused challenge rejection and revocation.
- Test a cash sale, split/mixed tender where supported, cancelled checkout,
  controlled refund, stock movement, receipt reprint, X reading and Z closure.

## Android signing setup

Managers agreed to arrange the existing Android signing key through the approved
secret-manager/GitHub setup. Preserve the current application's signing identity;
do not generate a replacement or publish a debug-signed release as a substitute.

The Android Gradle release expects these environment variables:

- `TIBATRACE_ANDROID_KEYSTORE`: secure temporary path to the existing keystore.
- `TIBATRACE_ANDROID_STORE_PASSWORD`
- `TIBATRACE_ANDROID_KEY_ALIAS`
- `TIBATRACE_ANDROID_KEY_PASSWORD`

Keep their values outside the repository and chat. A future GitHub build should
materialize the encrypted keystore secret only on its ephemeral runner, supply the
remaining secrets through masked environment variables, verify the expected
certificate fingerprint, and remove the temporary keystore after packaging.
