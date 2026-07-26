#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env.production}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

ENV_FILE="$(CDPATH= cd -- "$(dirname -- "${ENV_FILE}")" && pwd)/$(basename -- "${ENV_FILE}")"
export TIBATRACE_ENV_FILE="${ENV_FILE}"
COMPOSE="docker compose --env-file ${ENV_FILE} -f ${SCRIPT_DIR}/docker-compose.yml -f ${SCRIPT_DIR}/docker-compose.server.yml"

if grep -q '<[^>]*>' "${ENV_FILE}"; then
  echo "Environment file still contains placeholder values." >&2
  exit 1
fi

${COMPOSE} config --quiet
${COMPOSE} --profile maintenance run --rm migrate
${COMPOSE} up -d redis api worker beat hq
${COMPOSE} ps
