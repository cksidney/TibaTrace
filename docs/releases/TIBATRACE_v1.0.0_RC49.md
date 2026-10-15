# TibaTrace 1.0.0-rc49 — reachable intake and modal forms

People intake is available from the page header, each patient/practitioner/
customer registry tab, and the existing directory panels. Starting in the
platform overview opens an explicit active-pharmacy picker before the form.
Failed workspace selection cannot open intake. Customer records are reloaded
when the selected tenant changes; registration requests carry that tenant.

Prescription receipt and dispensing origination use separate modals. The
fulfilment desk opens draft, line, pick, package, seal, dispatch and delivery
evidence forms in modals. Commercial price-list creation, cloning and entry
editing, role creation, imported-item detail completion and opening setup also
use modals. Existing backend permissions, legal/clinical checks, independent
approval, price publication and quality-release gates still apply.

Shared modal behavior handles focus, Tab trapping, Escape, cancellation,
background scroll locking and busy dismissal. Refused or uncertain saves retain
the draft and existing retry key. Forms fit narrow screens without horizontal
overflow, and use opaque surfaces in both themes.

Audit scope: HQ People, Network, catalogue/imported setup, inventory,
procurement, sales/fulfilment, retail and B2B pricing, insurance, clinical,
regulatory, integration, access, reports and governance. Network, procurement,
inventory, insurance, regulatory, integration, catalogue/CSV and user creation
already have wired intake dialogs. Those remain in place. Read-only reporting,
health/GS1 lookup, unavailable external integrations and independent approval
requirements are not activated by bypassing their authoritative checks.

No backend source, database migration, native POS source, role grant or
production business-data seed is included. Signed Windows POS 1.0.7 remains the
managed installer. Synthetic local form tests do not create production patients,
prescriptions, orders, approvals or access grants.

Release acceptance requires application tests/typechecks/builds, browser form
checks, final-source production CI, image security/provenance, a fresh backup,
and live production verification. Deploy CI images by immutable digest and
retain rc48 source/images and its installer for rollback.
