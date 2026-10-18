# TibaTrace 1.0.0-rc61 — Windows POS installation clarity

Clarifies the Windows POS 1.1.0 managed-install flow in HQ and in the package
guide. Operators are told to use the authenticated managed-install ZIP, extract
it, and run its certificate-pinning installer script from elevated PowerShell.
The embedded setup EXE is not the first-run entry point on a new terminal.

Adds the missing POS 1.1.0 installation guide and replaces its stale fixed
version label with the release manifest version. No backend behavior, database
schema, migration, or Windows client binary changes are included. The existing
Windows 1.1.0 package remains the same signed artifact.

Release from the RC60 source only after the production image workflow passes.
Deploy the immutable RC61 image references using the production deployment
runbook, retain the RC60 image references for rollback, and verify HQ health and
the installer catalogue after activation.
