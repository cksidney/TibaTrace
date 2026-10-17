# POS activation and Manager acceptance

This checklist is operational acceptance, not a claim of regulatory certification.

## Independent activation workflow

1. An authorised tenant Manager creates a physical till in HQ **Finance & Cash
   Control → Register Physical Till**. Sign in on the real installation after
   completing any temporary-password change in HQ. In POS **Activation → Submit
   Activation Request**, choose the branch and available register by name and
   enter the device name and business justification. The native installation
   supplies its device ID and stable fingerprint. Only active branches and
   unassigned registers that can be opened appear as available. Requesting and enrolment require
   `identity.manage` or `tenant.pos_activation.request`; view-only authority cannot
   enrol a device. Creating the till separately requires device/identity management.
2. A different platform administrator reviews the request. Tenant role names and
   usernames do not grant platform authority. Approval and rejection require a
   rationale; a requester cannot review their own request. Approval rechecks the
   branch and register. Close any session and post its final Z report before
   approving a first-time installation.
3. In HQ **Administration & Users → POS Activations**, approval returns a challenge
   once, valid for 15 minutes. Give it directly to the requesting Manager. It is
   not a reusable activation credential. Windows refreshes approval status every
   15 seconds and has a manual refresh control; reopening the app is unnecessary.
4. Enrolment must supply the approved device ID and fingerprint. It rechecks that
   the branch and register are still active and ready, and that there is no open
   session or unreconciled prior session. It consumes the challenge, binds the
   register and returns a signed, expiring credential.
5. The credential lasts 365 days. `/api/v1/tenant/pos-activations/requests/validate/` checks it
   against durable approval, tenant/device/fingerprint, current register assignment,
   expiry and revocation. Client-side status alone is not approval.
6. Activation does not open the cash drawer session. A valid open branch business
   day is required. In **Register → Open register**, the authorised operator counts
   the opening float by denomination. This creates the register session and the
   accountable operator shift. Prior sessions require their final Z report.

## Recovery, renewal, suspension and replacement

- For a lost/expired approval code, or an enrolled installation with missing local
  credentials, a different explicit platform owner selects **Issue renewal /
  recovery code** with a 10–2000 character rationale. This invalidates the previous
  code and preserves the approved installation/branch/register identity. The old
  credential remains valid until its existing expiry, suspension/revocation, or
  successful replacement. Enrolling the new code rotates the credential and starts
  a new 365-day term; the old credential and consumed code are then refused.
- Native clients check encrypted-storage availability before sending an enrolment
  request. A storage write or lost network response can still fail after server
  enrolment. Restore storage and use the platform-owner recovery action on the
  existing request; creating a duplicate request or copying another till's token
  is not the recovery mechanism.
- **Suspend device** blocks trading immediately while retaining the register's
  cash accountability. **Resume device** requires a different platform owner from
  the original requester and a rationale. It preserves the original expiry; an
  expired or missing credential additionally needs renewal/recovery enrolment.
- For a replacement installation, close and reconcile the old register, revoke
  the old activation, then use **Release register for replacement**. Release
  refuses an open/closing register session, a previous session without a final Z
  report, or a conflicting activation. The new installation selects that available
  till, submits a fresh request and receives a new independent review. Historical
  sessions, reports and the revoked activation remain intact. This does not move
  an active till between branches or transfer an open cash session.
- A register and an installation cannot be reserved by competing pending, active
  or suspended activation requests. Requests and governance actions serialize on
  the tenant before changing the register assignment. No arbitrary commercial
  device quota is imposed; the UI does not claim quota enforcement.

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
use the protected `android-release` GitHub environment, materialize the base64
keystore only on its ephemeral runner, supply the remaining values as environment
secrets, verify the approved `TIBATRACE_ANDROID_CERT_SHA256` repository variable,
and remove the temporary keystore after packaging. The release workflow expects
environment secrets named `TIBATRACE_ANDROID_KEYSTORE_BASE64`,
`TIBATRACE_ANDROID_STORE_PASSWORD`, `TIBATRACE_ANDROID_KEY_ALIAS`, and
`TIBATRACE_ANDROID_KEY_PASSWORD`; configure required reviewers on that environment
before adding them. It runs only for a `pos-android-v<package-version>` tag and
publishes the APK, AAB, checksums and manifest only after signature verification.
