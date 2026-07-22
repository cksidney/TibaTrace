# ADR: DawaTrace Identity Strategy

- Status: Accepted for Phase 2
- Date: 2026-07-22

## Decision

DawaTrace stores users independently in `apps.identity.User`. Tenant roles grant
named capabilities; active attribute policies can deny a grant. A non-platform
user must belong to one tenant. Role assignment, external identity mapping, and
service accounts are tenant-owned.

Local password/JWT authentication is the Phase 2 baseline. JWTs contain the
DawaTrace product and tenant claim. `ExternalIdentityMapping` is the future OIDC/
SSO contract keyed by tenant, issuer, and subject; it has no Mercato user foreign
key. Service-account credentials are represented only by fingerprints, never raw
secrets.

## Identity Separation

- Patient: healthcare subject; never an implicit staff login.
- Practitioner: clinical professional identity, licence, and role.
- Staff user: authenticated human actor with RBAC/ABAC grants.
- Pharmacist/prescriber: practitioner role plus an appropriately authorized user.
- API client/service account: tenant-owned non-human principal contract.

## Reviewed Manager Exception

The user manager is intentionally available before tenant middleware so login can
resolve an identity. Authorization remains tenant-qualified. Every other
tenant-bearing model uses a fail-closed or explicit global-aware manager.

## Future Integration

OIDC authorization-code flow, issuer allowlists, key rotation, step-up
authentication, device authorization, and lifecycle provisioning are Phase 3.
