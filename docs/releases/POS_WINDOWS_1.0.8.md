# Windows POS 1.0.8 — workspace polish and TibaTrace branding

The Clinical, Retail and Print Centre entry screens now use a consistent navy and teal shell with labelled workspace icons, operator identity, compact operational status and responsive panels. The empty clinical queue offers search, refresh and a dispensing guide; patient safety information and the nine clinical steps appear after a prescription is selected. Register warnings remain visible and expand to the underlying notices and device facts.

Retail places the scoped Start new sale action next to the store selector, prevents concurrent sale operations, preserves refund work inside a collapsible panel and keeps the basket and settlement summary distinct. Print Centre adds real queue counts and filters, an installed-printer connection panel and concise setup instructions. Physical output still requires inspection and confirmation. Register and Sync Centre headings match the shell.

The existing TibaTrace logo is used without cropping. The Windows executable, NSIS installer and uninstaller explicitly use the TibaTrace ICO; the app sets its Windows application identity. The release workflow checks the actual executable and installer icon resources against the reference logo, alongside signing, managed installation and installed application launch.

Local validation: Windows renderer/main builds and typecheck passed; 114 POS tests passed. Synthetic browser checks covered queue search, episode navigation, shortcut help, locked shortcut containment, scoped draft creation, printer selection/setup and 1280/1024/390 layouts with no horizontal page overflow. No real transactions were created during interface testing.

Release via the immutable pos-windows-v1.0.8 tag. Publish the managed installer only after its Windows release job succeeds, signatures and archive checksums are verified, and the installed application check passes. Existing releases and minimum supported build remain unchanged.
