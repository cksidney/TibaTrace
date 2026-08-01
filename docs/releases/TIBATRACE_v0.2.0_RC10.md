# TibaTrace v0.2.0-rc10

Release candidate `0.2.0-rc10` fixes the Inventory Control stock-transfer
request entry point on top of the RC9 barcode and Reports release.

## Included changes

- makes **New transfer request** an actionable dialog trigger even when tenant
  inventory setup is incomplete;
- shows the exact missing custody-location and released-stock prerequisites
  inside the modal instead of presenting an inert disabled button;
- provides direct actions to review inventory locations or stock balances;
- keeps transfer submission disabled until there are at least two active
  locations and released stock at an active source location;
- retains server-side transfer validation, requester/approver segregation,
  FEFO dispatch, append-only ledger posting, and governed barcode matching; and
- adds UI regression coverage for both the trigger and fail-closed prerequisite
  state.

## Deployment

Backend and HQ images must be built by the production-images workflow from the
annotated release tag and deployed by immutable digest. Production retains RC9
as the sole rollback release after RC10 health and UI verification complete.
