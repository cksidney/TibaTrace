# TibaTrace Windows POS

The Windows client is an Electron application for queue review, clinical
screening, payment, counselling, and collection.

## Runtime guarantees

- API credentials are encrypted by Windows DPAPI and remain in Electron's main
  process.
- Renderer requests cross a restricted IPC boundary; arbitrary origins and
  token endpoints are rejected.
- Every API request carries the authenticated tenant and refreshes an expired
  access token once.
- Payments and collections are journaled with their idempotency keys before
  transmission. An interrupted outcome blocks further progression until it is
  reconciled.
- The packaged renderer has no Node access, no browser permissions, no external
  navigation, and a restrictive content-security policy.

## Development

Use Node.js 22.13 or newer in the Node 22 release line.

```bash
npm run build --workspace @dawatrace/shared
npm run typecheck --workspace @dawatrace/pos-windows
npm run test --workspace @dawatrace/pos-windows
npm run build --workspace @dawatrace/pos-windows
```

For a local Electron session, run Vite in one terminal:

```bash
npm run dev --workspace @dawatrace/pos-windows
```

Then launch Electron from PowerShell:

```powershell
$env:VITE_DEV_SERVER_URL = "http://127.0.0.1:5173"
$env:TIBATRACE_API_BASE_URL = "http://127.0.0.1:8000"
npm run start --workspace @dawatrace/pos-windows
```

HTTP is accepted only for localhost development. Production defaults to
`https://tibatrace.esenai.co.ke`.

## Windows release

Windows 10 build 19041 or newer is required. The Windows SDK supplies
`MakeAppx.exe` and `SignTool.exe`.

```powershell
$env:TIBATRACE_WINDOWS_PFX = "C:\secure\tibatrace-authenticode.pfx"
$env:TIBATRACE_WINDOWS_PFX_PASSWORD = "<secret>"
$env:TIBATRACE_WINDOWS_PUBLISHER = "CN=<exact certificate subject>"
npm run release:windows --workspace @dawatrace/pos-windows
```

The command produces a signed x64 MSIX in `apps/pos-windows/release`. It fails
when signing material is absent. Certificates and passwords must remain in the
release secret store, never in the repository.

Unsigned staged packages are CI evidence only and must not be distributed.
