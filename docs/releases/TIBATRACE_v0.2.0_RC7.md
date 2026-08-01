# TibaTrace v0.2.0-rc7

Release candidate `0.2.0-rc7` is the final HQ UI/UX and identity-governance
pass over the user-provisioning, POS activation, and till-installer workflows.

## Included changes

- replaced the inline Add User form with a responsive, accessible provisioning
  dialog, explicit staff identity fields, least-privilege role selection, and a
  one-time credential handoff;
- enforced accountable first and last names, valid usernames, and at least one
  tenant role in the authoritative identity API;
- added immutable audit events for user creation, account-status changes, role
  assignments, and administrator password resets without logging credentials;
- rebuilt the POS activation workspace around an explicit fail-closed service
  state while the authoritative activation API remains unavailable;
- moved Point of Sale Till Installers into the primary cash-control flow and
  replaced the overflowing release table with responsive, checksum-first cards;
- added release filters, operational impact, minimum-build guidance, and a
  secure download-review dialog for Windows and Android till packages.

## Activation-control status

The production backend does not expose the authoritative activation API in this
release. HQ therefore disables requests and decisions and clearly reports the
service as not connected. No approval, challenge, or credential is fabricated.

## Deployment

Backend and HQ images must be built by the production-images workflow from the
signed release tag and deployed by immutable digest. Production retains the
running release and exactly one rollback release; secrets, backups, database
volumes, and published POS artifacts remain outside release pruning.
