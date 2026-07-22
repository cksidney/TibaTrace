# ADR: Canonical DawaTrace Practitioner

- Status: Accepted for Phase 2
- Date: 2026-07-22

## Context

Mercato healthcare code represented staff users, prescribers, pharmacists, and
FHIR practitioners through overlapping model families. A login is not itself a
clinical identity, and a clinical identity may have multiple roles and licences.

## Decision

`apps.practitioners.Practitioner` is canonical. Identifiers, licences, and
organization/location roles are separate tenant-owned rows. `apps.identity.User`
is the authentication principal and may reference a professional staff ID, but it
does not replace the practitioner record.

## Preserved Fields

Name, status, contact data, professional identifiers, licence number/issuer/
validity, role code, organization, location, and active dates are preserved.

## Deprecated or Omitted

Generic employee roster fields, payroll data, cashier shifts, restaurant roles,
and duplicated pharmacy user profiles are outside this canonical model.

## Migration and Compatibility

Legacy practitioner and user identifiers use crosswalks. FHIR Practitioner and
PractitionerRole converters use only these canonical models. Same-tenant rules are
validated when roles and licences are saved.

## Risks

The mapping between migrated users and practitioners, professional-registry
verification, and licence renewal sources require Phase 3 integration decisions.
