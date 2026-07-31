#!/usr/bin/env bash
# Validate FHIR claim/preauth samples against Kenya eClaims IG (fhir.kenyaClaimsIG#0.1.0).
# Use for claims, preauthorization, and dispensing-for-reimbursement resources.
# Failures exit non-zero so CI treats them as build failures when samples exist.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAMPLES_DIR="$ROOT/backend/apps/fhir/samples/claims"
CACHE_DIR="${FHIR_VALIDATOR_CACHE:-$ROOT/.cache/fhir-validator}"
VERSION="${FHIR_VALIDATOR_VERSION:-6.3.23}"
JAR="$CACHE_DIR/validator_cli-${VERSION}.jar"
URL="https://github.com/hapifhir/org.hl7.fhir.core/releases/download/${VERSION}/validator_cli.jar"
IG="${FHIR_CLAIMS_IG:-fhir.kenyaClaimsIG#0.1.0}"

mkdir -p "$CACHE_DIR"
if [[ ! -f "$JAR" ]]; then
  echo "Downloading HL7 FHIR validator_cli ${VERSION}..."
  curl -fsSL -o "$JAR" "$URL"
fi

shopt -s nullglob
files=("$SAMPLES_DIR"/*.json)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No Claims IG samples under $SAMPLES_DIR — skipping (add samples when Claim converters land)."
  exit 0
fi

failed=0
for sample in "${files[@]}"; do
  echo "Validating $(basename "$sample") against R4 + ${IG}..."
  # Pull StructureDefinitions from artifacts / package registry — not base R4 alone.
  if ! java -jar "$JAR" "$sample" -version 4.0.1 -ig "$IG" -level error; then
    echo "FAILED: $sample" >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  echo "Kenya Claims IG validator reported errors." >&2
  exit 1
fi
echo "All Claims IG samples validated against ${IG}."
