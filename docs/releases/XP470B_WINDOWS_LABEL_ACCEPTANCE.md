# Xprinter XP-470B — Windows USB label acceptance

User-confirmed on 14 October 2026: **Xprinter XP-470B Barcode and Label Printer**.
The earlier connection choice is Windows USB. The receipt printer model and
actual label width/height are still unconfirmed. This is not a completed physical
installation or compatibility certification.

The user also supplied direct thermal, 203 DPI (8 dots/mm), up to 152 mm/s
and 108 mm maximum print-width specifications. These describe the device, not
the installed media: **108 mm is not a confirmed label width**, and no label
height or receipt-printer model has yet been supplied. Do not derive a paper
size or cash-drawer command from these specifications.

The [manufacturer specification](https://www.xprintertech.com/auto-calibration-mode-direct-thermal-barcode-printer-xp-470b)
lists 203 dpi direct thermal printing, USB, TSPL/ZPL/EPL/DPL emulation and a
108 mm maximum print width. Its
[official model/manual page](https://www.xprinter.net/companyfile/24.html)
is the starting point for approved model-matched driver/diagnostic downloads.
Do not substitute an unsigned third-party installer or infer a cash-drawer port
from the fact that this device prints barcodes.

## Manager acceptance

1. Install the approved XP-470B Windows driver, connect USB and print its driver
   test page. Confirm the exact Windows spooler name and actual media dimensions.
2. Calibrate the installed gap/black-mark media as directed by the model manual.
   Set the confirmed stock size and orientation in the Windows driver. Do not
   stretch a pharmacy label to a guessed size or bypass content checks.
3. In signed Windows POS 1.0.5 Print Centre, use the governed label job and Windows
   printer selector to choose the XP-470B. The current native path renders the
   approved document through the Windows driver; it does not send raw TSPL,
   ESC/POS, or a guessed cash-drawer pulse.
4. On a test/synthetic document, confirm one complete legible label, no clipping,
   no extra copy/feed. The existing medicine-label renderer is text-only: the
   printer's barcode capability does not mean TibaTrace currently emits a barcode
   on that document. Barcode-label authoring/scanning acceptance is a separate
   software contract; do not invent an identifier from missing supplier data.
   Check the physical printer
   before retrying an unknown result; a spooled job is not proof of paper output.
5. Validate the actual pharmacy label's approved medicine/unit/batch/expiry and
   instructions against the governed source. Never invent real source details
   solely to create an acceptance print.

The XP-470B is recorded as the **label** printer. The Managers must separately
identify the **receipt** printer and confirm the printer-connected drawer port,
approved driver settings and cash-only transaction/refund acceptance. No drawer
command or receipt-printer support is implied by the label model specification.
