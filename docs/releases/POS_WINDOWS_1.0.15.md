# Windows POS 1.0.15 (build 15)

Includes the RX intake and explicit deferred-scan status from 1.0.14. Corrects
the upload helper caption to describe file validation without claiming malware
scanning occurred. The deferred notice and stored source verdict remain visible.

Compatible with server rc59. This client-only correction changes no backend
code or database schema. The upgrade is advisory and the minimum supported
build is unchanged. Publish the signed managed package after its Windows gates
pass and the rc59 backend is active; 1.0.14 is superseded before tenant publication.
