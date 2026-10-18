# Android POS 1.1.0 (version code 7)

Updates the Android display version to the single-digit minor/patch policy.
Gradle now reads version and monotonically increasing version code directly from
package.json. The package ID remains `co.ke.esenai.tibatrace.pos`.

Sign with the existing TibaTrace production key, whose retained certificate
SHA-256 is `6a76fd12f1a5f93efff97ea0de0dac0958974d6d345212233b10f1b38a19ed36`.
Verify APK/AAB signatures, version code/name, package ID and artifact checksums
before publication. Do not generate a replacement signing identity.

This release includes the existing Android POS workflow; the direct RX upload
and camera intake workspace is currently a Windows feature. Do not present
Android as having feature parity that has not been implemented and verified.
