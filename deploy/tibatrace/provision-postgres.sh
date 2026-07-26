#!/bin/sh
set -eu

ENV_FILE="${1:-.env.production}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

set -a
. "${ENV_FILE}"
set +a

: "${TIBATRACE_DB_NAME:?Set TIBATRACE_DB_NAME in ${ENV_FILE}}"
: "${TIBATRACE_DB_USER:?Set TIBATRACE_DB_USER in ${ENV_FILE}}"
: "${TIBATRACE_DB_PASSWORD:?Set TIBATRACE_DB_PASSWORD in ${ENV_FILE}}"

case "${TIBATRACE_DB_NAME}" in
  *[!A-Za-z0-9_]*|"") echo "TIBATRACE_DB_NAME must contain only letters, numbers, and underscores." >&2; exit 1 ;;
esac
case "${TIBATRACE_DB_USER}" in
  *[!A-Za-z0-9_]*|"") echo "TIBATRACE_DB_USER must contain only letters, numbers, and underscores." >&2; exit 1 ;;
esac

sudo -u postgres psql \
  --set ON_ERROR_STOP=1 \
  --set db_name="${TIBATRACE_DB_NAME}" \
  --set db_user="${TIBATRACE_DB_USER}" \
  --set db_password="${TIBATRACE_DB_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION', :'db_user', :'db_password')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name')
\gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'db_name', :'db_user')
\gexec
SQL

echo "PostgreSQL database ${TIBATRACE_DB_NAME} is provisioned for ${TIBATRACE_DB_USER}."
