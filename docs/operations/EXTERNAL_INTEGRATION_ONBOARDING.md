# External integration onboarding

Status: **templates only — NOT CONNECTED**. The owner has no approved provider
endpoints or contacts yet. Do not interpret a template or a configured secret
reference as successful integration, licence verification or received money.

Run `python manage.py provision_integration_templates` to provision sandbox and
production templates for DHA HIE/HWR, PPB premises/products/alerts/recalls,
SHA/approved insurers and M-PESA. The operation is idempotent, creates no active
endpoint, sends no traffic and preserves existing provider configuration.

For each provider, collect the official onboarding contact, data-use agreement,
approved endpoint specification, authentication scheme, TLS host allow-list,
callback authentication/replay requirements and sandbox test cases. Store actual
secrets only in the deployment secret manager; the database holds reference names.
Implement and validate the official adapter contract before advancing activation.
Templates do not register an insurer or payment adapter automatically.

Required acceptance evidence:

- DHA/HWR: matched practitioner identity, current licence/authority and expiry;
  unknown, revoked, expired and unavailable lookups must not become VERIFIED.
- PPB: premises/product identity plus signed/authenticated recall notifications;
  deduplicated alerts, stock quarantine and tenant acknowledgement evidence.
- SHA/insurer: member eligibility, authorisation, claim submission/reconciliation;
  a simulated approval is not a production approval or insurer receivable.
- M-PESA: authoritative amount, approved merchant/account, authenticated callback,
  duplicate/timeout/reversal reconciliation; initiation is not settlement.
- All providers: sandbox evidence, independent security review, platform-owner
  approval, fail-closed outage handling and audited suspension/revocation.

Managers own the separate stock and hardware acceptance: confirm actual pack
units, counted quantities, batch numbers and expiry dates; test clean installation,
upgrade, scanner, printer, drawer and end-of-shift reconciliation on the real tills.
Missing clinical or stock evidence must stay blocked, not be fabricated.
