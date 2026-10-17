# Windows POS 1.0.12 — build 12

Polishes retail and clinical POS layouts after review of the Clinical, Retail, Register, Print Centre, Sync Centre and Activation tabs. The retail store selector stays within its card at narrow widths, and disabled future clinical steps remain readable. Existing checkout, payment, recovery and branding behaviour is preserved.

Release through the immutable `pos-windows-v1.0.12` tag. Publish the signed managed package only after the Windows release job passes signature, checksum, managed installation and launch checks, then publish the verified package in the authenticated tenant POS catalogue. Installing the managed package on each till is required to receive these Windows screen changes.
