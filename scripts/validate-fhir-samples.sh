#!/usr/bin/env bash
# Validate FHIR sample resources against HL7 FHIR R4 (4.0.1).
# Failures exit non-zero so CI treats them as build failures.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAMPLES_DIR="$ROOT/backend/apps/fhir/samples"
CACHE_DIR="${FHIR_VALIDATOR_CACHE:-$ROOT/.cache/fhir-validator}"
VERSION="${FHIR_VALIDATOR_VERSION:-6.3.23}"
JAR="$CACHE_DIR/validator_cli-${VERSION}.jar"
URL="https://github.com/hapifhir/org.hl7.fhir.core/releases/download/${VERSION}/validator_cli.jar"

mkdir -p "$CACHE_DIR"
if [[ ! -f "$JAR" ]]; then
  echo "Downloading HL7 FHIR validator_cli ${VERSION}..."
  curl -fsSL -o "$JAR" "$URL"
fi

shopt -s nullglob
files=("$SAMPLES_DIR"/*.json)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No FHIR samples found under $SAMPLES_DIR" >&2
  exit 1
fi

failed=0
for sample in "${files[@]}"; do
  echo "Validating $(basename "$sample") against FHIR R4 4.0.1..."
  if ! java -jar "$JAR" "$sample" -version 4.0.1 -level error; then
    echo "FAILED: $sample" >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "FHIR validator reported errors." >&2
  exit 1
fi
echo "All FHIR samples validated against R4 4.0.1."
