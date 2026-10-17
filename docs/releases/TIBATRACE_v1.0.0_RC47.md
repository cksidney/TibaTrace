# TibaTrace 1.0.0-rc47 — HQ layout and guided Windows dispensing

Groups the existing permission-filtered HQ navigation into functional sections,
compacts the header, and makes executive cards responsive and keyboard
accessible. Executive figures are explicitly labelled as examples because they
are not connected to live reporting. Removes the nonfunctional field-search
placeholder. The rc46 tenant/owner navigation boundary is preserved.

Windows POS 1.0.6 adds prescription, payment, handover, and history views,
return-to-queue navigation, a compact operational status bar, and shortcut help.
F10 opens handover without performing a financial or custody action. Shortcuts
are inactive behind the workstation lock and outside the clinical workspace;
help lists only implemented bindings. Returning to the queue or switching
episodes cannot interrupt an in-flight read or payment. Existing payment,
clinical, action-recovery, and collection gates remain authoritative.

Review added regression checks for locked-workstation shortcuts, help in other
workspaces, F10 navigation, duplicate payment prevention, in-flight selection,
and cleared-episode write refusal. Local application gates cover 447 tests
across HQ, Windows, Android, and shared code, plus typechecks/builds. Browser,
full migrated SQLite/PostgreSQL 16, runtime-image security, image provenance,
and signed Windows installation gates must pass on this exact release source.

No model migrations or production data seeding are included. The Stage 2D.2
prototype and draft validator are excluded: their unconditional success reports
are not release evidence. Android signing and physical printer/stock acceptance
remain separate existing requirements.

Deploy CI-published API/worker/beat and HQ images by immutable digest. Retain
rc46 images, source, and a fresh root-only database/configuration backup for
application rollback. Publish Windows 1.0.6 only after its signature and managed
installation checks pass; retain 1.0.5 as the prior managed installer.
