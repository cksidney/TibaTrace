# TibaTrace 1.0.0-rc60 — RX intake deployment packaging

Carries rc59's prescription intake, encrypted documents, explicit operator
deferral of malware scanning and tenant integration readiness. Unscanned uploads
remain labelled `NOT_SCANNED`; clinical approval is still required.

Fixes static asset compilation: the Docker build uses dedicated asset settings
with the production manifest storage, without needing a production encryption
key. Runtime settings still require that key and the normal production secrets.
No keys are generated or baked into the image. No new schema changes over rc59;
apply prescription migrations 0019 and 0020 over rc57.

Windows and Android POS now use version **1.1.0**, with independent build numbers
17 and 7. Windows includes RX intake and source review; Android's signed APK and
App Bundle use the existing production key. Direct RX uploads are currently a
Windows feature. Previous unpublished installer candidates remain historical.

Activate only after all release gates pass and verified protected backups exist.
Enable source uploads and explicitly defer scanning through the protected server
configuration. Keep document keys for recovery: rc57 cannot read new encrypted
objects. Tenant EMR/DHA, card/Daraja and VSCU configuration still require their
separate verified commissioning inputs.
