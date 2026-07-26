#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <npm-script>" >&2
  exit 64
fi

SCRIPT_NAME="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while IFS= read -r package_file; do
  workspace="$(dirname "${package_file}")"
  if node -e '
const fs = require("fs");
const packageJson = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
process.exit(packageJson.scripts?.[process.argv[2]] ? 0 : 1);
' "${package_file}" "${SCRIPT_NAME}"; then
    npm --prefix "${workspace}" run "${SCRIPT_NAME}"
  fi
done < <(find "${ROOT}/apps" "${ROOT}/packages" -mindepth 2 -maxdepth 2 -name package.json -type f | sort)
