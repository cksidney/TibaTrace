# Windows POS 1.0.13 (build 13)

Adds Clinical → Receive prescription and Received prescriptions: direct RX
entry, camera photos, JPEG/PNG/PDF uploads with source preview, scoped inbox,
legal/CDS review and pharmacist verification. Unknown intake outcomes reconcile
using the original command before a retry. Tenant EMR/DHA feeds require explicit
commissioned connectors and identity/product maps. Source approvals never grant
clinical approval or release stock.

Includes tenant card-provider and Daraja readiness, unsettled tender balance
handling and recovery safeguards. Requires the rc58 backend, clinical document
keyring and private scanner for RX intake. Existing installations receive an
advisory upgrade; this release does not force a new minimum supported build.

The signed managed installation package must pass branding, signature,
timestamp, clean installation and secure bridge checks before tenant publication.
