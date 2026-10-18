# Windows POS 1.1.1 (build 18)

Compacts oversized POS dialogs and trims excess whitespace across the Clinical,
Retail, Register, Print Centre, Sync Centre and Activation workspaces. RX intake
uses a narrower, scrollable dialog; action dialogs share a compact layout, and
short empty states no longer reserve large blank panels. Long prescription
content remains scrollable, controls retain touch-friendly sizing, and phone
layouts keep their narrow-screen gutters.

This is an advisory Windows client update with no backend or database changes.
The minimum supported build remains unchanged. Release through the immutable
`pos-windows-v1.1.1` tag after the signing, managed-install and clean Windows
launch checks pass; then publish the verified package to the tenant POS
catalogue. Existing tills receive the changes after installing the managed
package.
