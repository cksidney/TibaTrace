# TibaTrace POS Visual Regression Report

## World-Class UI/UX Design Certification

Windows has an existing Playwright visual harness for its clinical component
catalogue. It checks approved screenshots, non-zero rendered dimensions and
horizontal overflow for each declared scenario. Pixel baseline paths are now
separated by viewport project, and pixel assertions run only on CI where a
reviewed baseline is authoritative. Local runs still execute the structural
rendering and overflow checks without creating unreviewed screenshots.

This pass did not add a retail or Android device visual suite because the
required emulator/device profiles and baseline review are not available in this
environment.

On 2026-07-28, the local structural suite passed for both `1280×900` and
`1024×768`: 64 checks passed and 31 CI-only screenshot checks were skipped per
project. No local screenshot was accepted as a baseline.

Required evidence remains outstanding for Windows 1366×768, 1440×900 and
1920×1080; Android 8-, 10- and 12-inch tablet layouts; retail, payment,
printing, Sync Centre, offline and shift-close states. Until those runs are
captured and reviewed, no visual-regression certification is claimed.
