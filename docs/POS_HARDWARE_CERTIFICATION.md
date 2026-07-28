# TibaTrace POS Hardware Certification

**Assessment date:** 2026-07-28  
**Decision:** `BLOCKED`

This is a hardware evidence record, not a simulator or production certificate.

| Capability | Status | Evidence |
|---|---|---|
| Windows keyboard workflow | SIMULATOR VALIDATED | Renderer production build and keyboard unit tests pass. |
| Windows barcode scanner | NOT IMPLEMENTED | Retail scan input accepts keyboard-wedge data; no physical scanner has been tested. |
| Windows 58 mm printer | NOT IMPLEMENTED | No transport or physical validation. |
| Windows 80 mm printer | NOT IMPLEMENTED | No transport or physical validation. |
| Windows spooler | NOT IMPLEMENTED | No print-job or spooler adapter exists. |
| ESC/POS USB | NOT IMPLEMENTED | No transport exists. |
| ESC/POS network | NOT IMPLEMENTED | No transport exists. |
| Android camera scan | NOT IMPLEMENTED | No camera scanner adapter exists. |
| Android hardware scanner | NOT IMPLEMENTED | Retail scan input exists; no physical scanner has been tested. |
| Android Bluetooth printer | NOT IMPLEMENTED | No transport exists. |
| Android network printer | NOT IMPLEMENTED | No transport exists. |
| Cash drawer | NOT IMPLEMENTED | No drawer integration exists. |
| Android process restart | SIMULATOR VALIDATED | Secure-session and action-journal tests pass; no physical-device evidence exists. |
| Network interruption | BLOCKED | No retail Sync Centre or offline transaction policy is implemented. |

No row above labelled `SIMULATOR VALIDATED` may be read as physical-device
validation. Physical certification requires a recorded test on the named model,
transport, OS version and released POS package.
