# TibaTrace v0.2.0-rc8

Release candidate `0.2.0-rc8` completes the Reports reporting-window workflow
and deploys its UI and server-side governance as one immutable release.

## Included changes

- added responsive reporting-window presets, custom start and end date-time
  controls, and hourly through yearly aggregation selection;
- added immediate invalid-range feedback and disabled exports until the period
  is complete and ordered correctly;
- normalized report periods to UTC and enforced the same date-time and
  granularity rules in the authoritative download API;
- embedded the selected reporting window and aggregation in JSON, CSV, Excel-
  compatible, and PDF exports;
- included the window in the tamper-evident receipt digest, validation QR,
  immutable audit event, and receipt-validation response; and
- kept report content explicitly described as an authenticated tenant snapshot,
  so the UI does not imply unsupported domain-level historical filtering.

## Deployment

Backend and HQ images must be built by the production-images workflow from the
signed release tag and deployed by immutable digest. Production retains the
running release and exactly one rollback release; secrets, backups, database
volumes, and published POS artifacts remain outside release pruning.
