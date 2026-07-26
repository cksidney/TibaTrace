#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${TIBATRACE_API_BASE_URL:=https://tibatrace.esenai.co.ke}"
: "${TIBATRACE_ANDROID_KEYSTORE:?Set TIBATRACE_ANDROID_KEYSTORE.}"
: "${TIBATRACE_ANDROID_STORE_PASSWORD:?Set TIBATRACE_ANDROID_STORE_PASSWORD.}"
: "${TIBATRACE_ANDROID_KEY_ALIAS:?Set TIBATRACE_ANDROID_KEY_ALIAS.}"
: "${TIBATRACE_ANDROID_KEY_PASSWORD:?Set TIBATRACE_ANDROID_KEY_PASSWORD.}"

if [[ "${TIBATRACE_API_BASE_URL}" != https://* ]]; then
  echo "TIBATRACE_API_BASE_URL must use HTTPS." >&2
  exit 1
fi

cd "${ROOT}"
npm run android:bundle:release --workspace @dawatrace/pos-android
