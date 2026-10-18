# TibaTrace 1.0.0-rc58 — RX intake and tenant integration readiness

Windows POS 1.0.13 (build 13) adds direct RX intake, camera capture,
JPEG/PNG/PDF source upload and preview, a branch intake inbox and governed
legal, clinical and pharmacist review before dispensing. EMR/DHA imports use
explicit tenant connectors and patient, prescriber and product mappings.

This release includes reviewed payment provider readiness and preserves rc57's
activation recovery and single fiscal outbox. It also carries register/business
day controls and clinical document encryption. External feeds and payment
providers remain disabled until commissioned per tenant.

Apply prescription migrations 0019 and 0020. Configure a versioned document
keyring and private malware scanner before activation. No secrets belong in the
source release. Production RX intake remains fail-closed without CLEAN scanning.

Deployment is pending exact-source CI, signed Windows installer acceptance,
protected pre-deployment backups and the supplied scanner endpoint. Physical
hardware certification and statutory/privacy sign-off are separate evidence
requirements; this release does not claim them complete.

Rollback must retain document keys and clinical objects. rc57 cannot read newly
encrypted documents: if the new release has accepted writes, use a compatible
forward fix or a specifically reviewed recovery plan; do not blindly restore an
older database or discard post-deployment transactions.
