#!/usr/bin/env bash
set -euo pipefail

release_scan_image=${1:?image reference required}
release_scan_output=${2:?JSON evidence path required}
release_scan_sha=${3:?exact source SHA required}
release_scan_kind=${4:?backend or hq required}
case "$release_scan_kind" in backend|hq) ;; *) exit 2 ;; esac
release_scan_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
release_scan_directory=$(dirname "$release_scan_output")
mkdir -p "$release_scan_directory"
release_scan_directory=$(cd "$release_scan_directory" && pwd)
release_scan_filename=$(basename "$release_scan_output")
release_scan_cache=$(mktemp -d /tmp/tibatrace-trivy-cache.XXXXXX)

# Local Docker inspection only: no production environment or registry token is
# mounted. No .trivyignore or ignore-unfixed exception can hide a release defect.
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$release_scan_directory:/evidence" \
  -v "$release_scan_cache:/root/.cache/trivy" \
  aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa \
  image --image-src docker --platform linux/amd64 --scanners vuln \
  --disable-telemetry --no-progress --ignorefile /dev/null --list-all-pkgs \
  --format json --output "/evidence/$release_scan_filename" "$release_scan_image"

release_scan_options=()
if [[ "$release_scan_kind" == backend ]]; then release_scan_options+=(--backend); fi
python3 "$release_scan_root/scripts/validate_container_scan.py" \
  "$release_scan_output" --image "$release_scan_image" --source-sha "$release_scan_sha" "${release_scan_options[@]}"
