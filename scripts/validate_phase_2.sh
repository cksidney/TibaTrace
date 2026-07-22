#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
PYTEST="${ROOT}/.venv/bin/pytest"

export DJANGO_SETTINGS_MODULE=dawatrace.settings.test
export DAWATRACE_DATABASE_URL="sqlite:///${ROOT}/artifacts/generated/tests/phase2.sqlite3"
export DAWATRACE_REDIS_URL=locmem://
export DAWATRACE_CELERY_TASK_ALWAYS_EAGER=true
export DAWATRACE_SECRET_KEY=test-only-not-a-secret
export DAWATRACE_OBJECT_SIGNING_KEY=test-document-signing-key

mkdir -p "${ROOT}/artifacts/generated/tests" "${ROOT}/artifacts/generated/security"
rm -f "${ROOT}/artifacts/generated/tests/phase2.sqlite3"

"${ROOT}/.venv/bin/pip" check
"${ROOT}/.venv/bin/ruff" check "${ROOT}/backend/apps" "${ROOT}/backend/dawatrace" "${ROOT}/backend/tests"
"${PYTHON}" "${ROOT}/backend/manage.py" check --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" makemigrations --check --dry-run --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate prescription 0001 --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate prescription --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate cds 0003 --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate cds --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate fhir 0001 --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate fhir --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate crosswalks zero --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate crosswalks --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate documents zero --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" migrate documents --noinput --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" audit_clinical_lookup_safety --settings=dawatrace.settings.test
"${PYTHON}" "${ROOT}/backend/manage.py" audit_tenant_managers --settings=dawatrace.settings.test
"${PYTEST}" -c "${ROOT}/backend/pytest.ini" "${ROOT}/backend/tests" -q \
  --junitxml="${ROOT}/artifacts/generated/tests/backend.xml"
"${ROOT}/.venv/bin/bandit" -q -r "${ROOT}/backend/apps" "${ROOT}/backend/dawatrace" \
  -c "${ROOT}/pyproject.toml" -f json -o "${ROOT}/artifacts/generated/security/bandit.json"
"${ROOT}/.venv/bin/cyclonedx-py" requirements "${ROOT}/backend/requirements.lock" \
  --output-reproducible --of JSON -o "${ROOT}/artifacts/generated/security/dawatrace-backend.cdx.json"
"${PYTHON}" "${ROOT}/scripts/scan_secrets.py" \
  --root "${ROOT}" --output "${ROOT}/artifacts/generated/security/secret-scan.json"
npm --prefix "${ROOT}" run typecheck
npm --prefix "${ROOT}" run build

if [[ "${DAWATRACE_RUN_ONLINE_AUDIT:-false}" == "true" ]]; then
  "${ROOT}/.venv/bin/pip-audit" -r "${ROOT}/backend/requirements.lock" \
    --format json --output "${ROOT}/artifacts/generated/security/pip-audit.json"
fi
