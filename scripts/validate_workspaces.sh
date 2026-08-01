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
  # packages/ before apps/: the apps import @dawatrace/shared through its
  # exports map, which resolves into packages/shared/dist. Sorting the two
  # trees together put apps/hq-web first, so a `build` run succeeded only when
  # a previous run had left dist on disk -- and failed in a clean container.
done < <({
  find "${ROOT}/packages" -mindepth 2 -maxdepth 2 -name package.json -type f | sort
  find "${ROOT}/apps" -mindepth 2 -maxdepth 2 -name package.json -type f | sort
})
