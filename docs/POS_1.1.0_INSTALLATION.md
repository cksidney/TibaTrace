# POS 1.1.0 installation

Both platforms display **1.1.0**. Their internal build counters are independent:
Windows build 17 and Android version code 7. Versions now carry from `1.0.9` to
`1.1.0`; old immutable candidate tags are retained as history.

## Windows

After server activation and catalogue publication, sign into HQ and open
**Finance & Cash Control → Point of Sale Till Installers**. Download Windows 1.1.0's managed installation ZIP, extract it
and follow its `INSTALLATION-GUIDE.md`. Use the included managed installation
script so the signing certificate is verified and enrolled correctly.

The package passed signing, timestamp, clean-install and secure bridge checks.
Package SHA-256:
`b3ebabd249384ca2cce580d1cecb0de5447519367ee55afe711e1c27d6081ab6`.

## Android

Download Android 1.1.0's APK from the same HQ installer section after publication. It
supports Android 7.0+ (API 24), ARM64 devices. Install it as an update over the
existing TibaTrace app; do not uninstall the old app as part of an upgrade.
If Android prompts to allow installation from the browser or file manager,
allow that source for this installation under your device-management policy.

The APK uses the same production certificate and package ID as the previous HQ
APK. Installation over that APK, unchanged app UID and startup were verified in
an isolated Android 14 emulator. No tenant sign-in or patient data was used.
APK SHA-256:
`3a3a626cf6dc2833c38ab7a0f168e1b9b9f42e367e5d1141a4b33ff0ce662a27`.
The signed Android App Bundle is also retained with the GitHub release for
managed distribution. Physical payment/printer hardware needs its own checks.

## Prescription sources and scanning

In Windows, open **Clinical → Receive prescription** for direct intake and
photo/PDF sources. The server is prepared for the operator-requested scanning
deferral: uploaded sources are explicitly **Not malware scanned**. Encryption,
file validation, permissions and pharmacist review still apply. ClamAV can be
commissioned later; enabling it does not certify earlier uploads.

The Android app does not yet include the direct RX photo/PDF intake workspace.
Use the Windows Clinical workspace for that intake. External clinical feeds and
card/Daraja providers require separate commissioning per tenant.
