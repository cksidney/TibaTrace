# POS Offline Clinical Safety

The offline clinical safety framework ensures continuous screening capability during network outages while maintaining regulatory and patient safety controls.

## Offline Operational States

- **`ONLINE_VERIFIED`**: Full real-time connection to central `apps.cds` engine.
- **`OFFLINE_CACHE_VALID`**: Operates on verified local rules bundle within validity window.
- **`OFFLINE_LIMITED`**: Package expired or incomplete; permits low-risk sales only with warning banners.
- **`OFFLINE_BLOCKED`**: High-risk or controlled medicine transactions strictly prohibited until connection restored.

## Safety Package Architecture

- **Contents**: Compiled CDS safety rules, active ingredient crosswalks, drug interaction matrices, and controlled medicine classifications.
- **Security**: Packages are HMAC-SHA256 signed, versioned, tenant-scoped, and expiry-controlled.

## Offline Policy Matrix

- **Over-the-Counter (OTC)**: Evaluated against local cache; allowed under `OFFLINE_CACHE_VALID` and `OFFLINE_LIMITED`.
- **Prescription Only (POM)**: Requires valid local package; high/critical findings require pharmacist review.
- **Controlled Substances**: Dispensing strictly blocked when in `OFFLINE_LIMITED` or `OFFLINE_BLOCKED` state.
