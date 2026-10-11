# TibaTrace v1.0.0-rc23 — security and payment hardening

This release addresses the live audit's critical Bearer-token tenant-scope and
suspension bypass. JWT identity is validated before tenant context is accepted.
Workspace headers cannot expand a tenant user's authority; malformed and
unknown workspace IDs fail closed. Platform scope is an explicit exception.

Temporary passwords now gate protected routes and HQ supplies a mandatory
self-service change screen. Password changes invalidate old JWT credentials.
HQ aggregate patient/clinical/audit rows respect the authenticated actor's
capabilities; source-item setup requires commercial setup authority; report
receipts are validated within the selected tenant.

B2B price maintenance requires pricing authority and a recorded reason; its
creation route now assigns tenant ownership correctly. Price-book GETs no
longer bootstrap data. Clinical catalogue activation requires explicit authority.
Direct payment-intent lookups are tenant-bound, and amount requests must match
the authoritative linked order. Settlement listing uses its own serializer.
Simulated payment initiation and callbacks cannot settle a real production
tenant. Browser `/pos/` is included in both proxy route templates.
Simulated insurer eligibility, preauthorisation and claim submission are likewise
blocked for real production tenants. Till PINs cannot bypass the initial system
password-change requirement. Reused payment-intent keys reject different payloads.

Demo tests replay at their declared scenario date; demo transfer planning reaches
empty dispensaries with compatible storage. Stock validators distinguish reserved
quantity from physical on-hand movement. Real expiry and clinical guards remain
unchanged. The malformed FHIR workflow is repaired and production image publishing
now depends on full migrated backend tests, lint, drift and all Node 22 app gates.

An additive provider-choice migration supports disabled SHA/insurer and M-PESA
onboarding templates alongside DHA/PPB. Provisioning preserves existing settings,
creates no active endpoint, stores no secret and makes no network request.
Integration management and national platform routes require explicit platform
authority. Existing accounts keep their passwords and
role assignments. Users marked for initial password change must complete it
before entering the workspace; legacy JWTs must sign in again.

This is a security mitigation release, **not** full trading certification.
Retail completion, current native installers, device activation, opening-stock
publication and reporting semantics remain subsequent
acceptance items. Detailed verification is recorded in the closure evidence.
