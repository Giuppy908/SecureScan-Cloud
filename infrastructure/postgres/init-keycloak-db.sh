#!/usr/bin/env bash
set -euo pipefail

# Bootstrap minimale del database Keycloak nello stesso PostgreSQL usato anche
# dall'applicazione. La separazione logica tra `securescan` e `keycloak`
# riduce l'accoppiamento tra dati applicativi e dati IAM senza introdurre un
# secondo container database.
#
# Questo script viene eseguito dal Docker Official Image PostgreSQL soltanto
# durante la prima inizializzazione del volume dati. Se il volume esiste gia`,
# `/docker-entrypoint-initdb.d/` non viene rieseguito automaticamente.

required_vars=(
  KEYCLOAK_DB_NAME
  KEYCLOAK_DB_USERNAME
  KEYCLOAK_DB_PASSWORD
  POSTGRES_DB
  POSTGRES_USER
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Variabile richiesta mancante per il bootstrap Keycloak: ${var_name}" >&2
    exit 1
  fi
done

if [[ "${KEYCLOAK_DB_NAME}" == "${POSTGRES_DB}" ]]; then
  echo "KEYCLOAK_DB_NAME deve essere distinto da POSTGRES_DB in production." >&2
  exit 1
fi

if [[ "${KEYCLOAK_DB_USERNAME}" == "${POSTGRES_USER}" ]]; then
  echo "KEYCLOAK_DB_USERNAME deve essere distinto da POSTGRES_USER in production." >&2
  exit 1
fi

# Le query usano `\gexec` per restare idempotenti quando il bootstrap parte su
# un volume nuovo ma l'immagine PostgreSQL viene ricreata piu` volte prima del
# primo shutdown completo.
psql \
  --quiet \
  --set ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --set keycloak_db_name="${KEYCLOAK_DB_NAME}" \
  --set keycloak_db_username="${KEYCLOAK_DB_USERNAME}" \
  --set keycloak_db_password="${KEYCLOAK_DB_PASSWORD}" <<'EOSQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'keycloak_db_username',
  :'keycloak_db_password'
)
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_catalog.pg_roles
  WHERE rolname = :'keycloak_db_username'
)\gexec

SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'keycloak_db_name',
  :'keycloak_db_username'
)
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_database
  WHERE datname = :'keycloak_db_name'
)\gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'keycloak_db_name')\gexec
SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'keycloak_db_name', :'keycloak_db_username')\gexec
EOSQL
