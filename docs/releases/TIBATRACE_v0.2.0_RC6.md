# TibaTrace v0.2.0-rc6

Release candidate `0.2.0-rc6` consolidates every HQ, browser POS, Android POS,
and Windows POS change produced after `rc5`.

## Included changes

- responsive HQ access, procurement, tenant, and user-management refinements;
- improved browser POS layouts and interaction feedback;
- expanded Android clinical dispensing, print, and synchronisation workflows;
- expanded Windows clinical review, prescription, print, register, and sync workflows;
- POS activation policy types, tests, compliance evidence, and fail-closed client surfaces;
- Windows POS `1.0.2` and Android POS `0.1.0-alpha.4` packaging metadata;
- release-gate fixes for Python linting, demo-seed validation, and strict TypeScript optional properties.

## Activation-control status

The clients do not manufacture or cache approval results. Activation requests,
approvals, challenges, and credentials fail closed unless an authoritative API
confirms them. The production backend does not yet expose the activation API,
so these controls remain visibly unavailable rather than simulating success.

## Deployment

Backend and HQ images must be built by the production-images workflow from the
signed release tag. POS artifacts must be built and signed from their versioned
release workflows. Production retains the running release and one rollback
release only.
