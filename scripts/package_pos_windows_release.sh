#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${TIBATRACE_API_BASE_URL:=https://tibatrace.esenai.co.ke}"
: "${TIBATRACE_WINDOWS_PFX:?Set TIBATRACE_WINDOWS_PFX to the Authenticode PFX path.}"
: "${TIBATRACE_WINDOWS_PFX_PASSWORD:?Set TIBATRACE_WINDOWS_PFX_PASSWORD.}"
: "${TIBATRACE_WINDOWS_PUBLISHER:?Set TIBATRACE_WINDOWS_PUBLISHER to the certificate subject.}"

if [[ "${TIBATRACE_API_BASE_URL}" != https://* ]]; then
  echo "TIBATRACE_API_BASE_URL must use HTTPS." >&2
  exit 1
fi

cd "${ROOT}"
npm run build --workspace @dawatrace/pos-windows
pwsh -NoProfile -File scripts/package_pos_windows.ps1 -RequireSigning
