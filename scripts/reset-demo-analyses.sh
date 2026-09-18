#!/usr/bin/env bash
set -euo pipefail

# Reset locale delle sole analisi demo di SecureScan Cloud.
# Uso previsto: sviluppo/demo locale con Docker Compose.
# Lo script elimina esclusivamente:
# - i record della tabella analyses
# - gli eventuali file residui in /data/uploads
#
# Lo script NON tocca:
# - /data/avatars
# - user_profiles
# - worker_heartbeats
# - api_instance_heartbeats
# - alembic_version
# - Keycloak, ruoli, configurazioni o altri volumi
#
# Non usare in ambienti production senza revisione esplicita.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
COMPOSE_FILE="${REPO_ROOT}/infrastructure/compose/compose.yaml"
POSTGRES_SERVICE="postgres"
UPLOAD_STORAGE_SERVICE="upload-storage-init"
QUIESCED_SERVICES=("analysis-api-1" "analysis-api-2" "analysis-worker")
UPLOADS_DIR="/data/uploads"
AVATARS_DIR="/data/avatars"
DRY_RUN=false
STOPPED_SERVICES=()
SERVICES_QUIESCED=false

if [[ $# -gt 0 ]]; then
  for argument in "${@}"; do
    case "${argument}" in
      --dry-run)
        DRY_RUN=true
        ;;
      *)
        echo "Argomento non riconosciuto: ${argument}" >&2
        echo "Uso: $0 [--dry-run]" >&2
        exit 1
        ;;
    esac
  done
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "File Compose non trovato: ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "File .env non trovato: ${ENV_FILE}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker non disponibile nel PATH." >&2
  exit 1
fi

docker_compose() {
  # Centralizza l'invocazione di Docker Compose per evitare che lo script
  # usi file o env diversi da quelli della demo locale canonica.
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

psql_exec() {
  # Tutta la parte database passa dal container PostgreSQL gia` in esecuzione:
  # non viene mai aperta una connessione diretta esterna dal Mac.
  local sql="$1"
  docker_compose exec -T "${POSTGRES_SERVICE}" sh -lc "
    PGPASSWORD=\"\${POSTGRES_PASSWORD}\" \
    psql \
      -v ON_ERROR_STOP=1 \
      -U \"\${POSTGRES_USER}\" \
      -d \"\${POSTGRES_DB}\" \
      -At \
      -F '|' \
      -c \"${sql}\"
  " < /dev/null
}

find_upload_runner() {
  # Il reset deve poter montare il volume condiviso /data anche mentre API e
  # worker sono fermi. Per questo usa il servizio helper dedicato allo storage.
  printf '%s\n' "${UPLOAD_STORAGE_SERVICE}"
}

storage_exec() {
  local runner="$1"
  shift
  if [[ "${runner}" == "${UPLOAD_STORAGE_SERVICE}" ]]; then
    docker_compose run --rm --no-deps --entrypoint sh "${runner}" -lc "$*" < /dev/null
    return
  fi

  docker_compose exec -T "${runner}" sh -lc "$*" < /dev/null
}

restore_services() {
  # Ripristina solo i servizi che erano realmente attivi prima del reset,
  # cosi` lo script non forza stati inattesi in ambienti locali gia` parziali.
  local service

  if [[ "${SERVICES_QUIESCED}" != "true" || "${#STOPPED_SERVICES[@]}" -eq 0 ]]; then
    return
  fi

  echo
  echo "Ripristino servizi applicativi precedentemente attivi..."
  for service in "${STOPPED_SERVICES[@]}"; do
    docker_compose up -d "${service}" >/dev/null
  done
}

trap restore_services EXIT

quiesce_services() {
  # La quiescenza evita race condition: durante la finestra distruttiva nessuna
  # API puo` creare nuove analisi e nessun worker puo` aggiornare record appena
  # cancellati o ripopolare /data/uploads.
  local service
  STOPPED_SERVICES=()

  for service in "${QUIESCED_SERVICES[@]}"; do
    if docker_compose ps --status running --services | grep -Fxq "${service}"; then
      STOPPED_SERVICES+=("${service}")
    fi
  done

  if [[ "${#STOPPED_SERVICES[@]}" -eq 0 ]]; then
    SERVICES_QUIESCED=true
    return
  fi

  echo
  echo "Arresto temporaneo dei servizi applicativi per evitare race condition..."
  docker_compose stop "${STOPPED_SERVICES[@]}" >/dev/null
  SERVICES_QUIESCED=true
}

if ! docker_compose ps --status running --services | grep -Fxq "${POSTGRES_SERVICE}"; then
  echo "Il servizio PostgreSQL non risulta in esecuzione." >&2
  exit 1
fi

if ! psql_exec "SELECT 1;" >/dev/null; then
  echo "Impossibile raggiungere PostgreSQL tramite Docker Compose." >&2
  exit 1
fi

UPLOAD_RUNNER="$(find_upload_runner)"

db_snapshot_raw="$(
  psql_exec "
SELECT
  COUNT(*)::text,
  COALESCE(MIN(sequence_number), 0)::text,
  COALESCE(MAX(sequence_number), 0)::text
FROM analyses;
SELECT last_value::text, is_called::text
FROM analyses_sequence_number_seq;
"
)"
db_snapshot_line_1="$(printf '%s\n' "${db_snapshot_raw}" | sed -n '1p')"
db_snapshot_line_2="$(printf '%s\n' "${db_snapshot_raw}" | sed -n '2p')"

if [[ -z "${db_snapshot_line_1}" || -z "${db_snapshot_line_2}" ]]; then
  echo "Snapshot database incompleto: impossibile proseguire." >&2
  exit 1
fi

IFS='|' read -r analyses_count analyses_min analyses_max <<<"${db_snapshot_line_1}"
IFS='|' read -r sequence_last_value sequence_is_called <<<"${db_snapshot_line_2}"

uploads_count="$(
  storage_exec "${UPLOAD_RUNNER}" "
    if [ -d '${UPLOADS_DIR}' ]; then
      find '${UPLOADS_DIR}' -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' '
    else
      echo 0
    fi
  "
)"

avatars_count_before="$(
  storage_exec "${UPLOAD_RUNNER}" "
    if [ -d '${AVATARS_DIR}' ]; then
      find '${AVATARS_DIR}' -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' '
    else
      echo 0
    fi
  "
)"

echo "Anteprima reset analisi demo"
echo "  Analisi presenti: ${analyses_count}"
echo "  sequence_number min/max: ${analyses_min}/${analyses_max}"
echo "  Sequence analyses_sequence_number_seq: last_value=${sequence_last_value}, is_called=${sequence_is_called}"
echo "  File presenti in ${UPLOADS_DIR}: ${uploads_count}"
echo "  File presenti in ${AVATARS_DIR}: ${avatars_count_before}"
echo "  Helper storage usato: ${UPLOAD_RUNNER}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo
  echo "Dry-run completato: nessuna modifica eseguita."
  exit 0
fi

echo
echo "Questa operazione eliminerà solo i record di analyses e i file residui in ${UPLOADS_DIR}."
echo "Per confermare digita esattamente RESET"
read -r confirmation

if [[ "${confirmation}" != "RESET" ]]; then
  echo "Conferma non valida. Nessuna modifica eseguita."
  exit 0
fi

quiesce_services

psql_exec "
BEGIN;
DELETE FROM analyses;
ALTER SEQUENCE analyses_sequence_number_seq RESTART WITH 1;
COMMIT;
" >/dev/null

storage_exec "${UPLOAD_RUNNER}" "
  if [ -d '${UPLOADS_DIR}' ]; then
    find '${UPLOADS_DIR}' -mindepth 1 -maxdepth 1 -type f -delete
  fi
" >/dev/null

final_snapshot_raw="$(
  psql_exec "
SELECT COUNT(*)::text FROM analyses;
SELECT last_value::text, is_called::text FROM analyses_sequence_number_seq;
"
)"
final_snapshot_line_1="$(printf '%s\n' "${final_snapshot_raw}" | sed -n '1p')"
final_snapshot_line_2="$(printf '%s\n' "${final_snapshot_raw}" | sed -n '2p')"

if [[ -z "${final_snapshot_line_1}" || -z "${final_snapshot_line_2}" ]]; then
  echo "Verifica finale incompleta dopo il reset." >&2
  exit 1
fi

final_analyses_count="${final_snapshot_line_1}"
IFS='|' read -r final_sequence_last_value final_sequence_is_called <<<"${final_snapshot_line_2}"

final_uploads_count="$(
  storage_exec "${UPLOAD_RUNNER}" "
    if [ -d '${UPLOADS_DIR}' ]; then
      find '${UPLOADS_DIR}' -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' '
    else
      echo 0
    fi
  "
)"

avatars_count_after="$(
  storage_exec "${UPLOAD_RUNNER}" "
    if [ -d '${AVATARS_DIR}' ]; then
      find '${AVATARS_DIR}' -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' '
    else
      echo 0
    fi
  "
)"

if [[ "${final_analyses_count}" != "0" ]]; then
  echo "Errore: la tabella analyses non è vuota dopo il reset." >&2
  exit 1
fi

if [[ "${final_uploads_count}" != "0" ]]; then
  echo "Errore: ${UPLOADS_DIR} contiene ancora file dopo il reset." >&2
  exit 1
fi

if [[ "${avatars_count_after}" != "${avatars_count_before}" ]]; then
  echo "Errore: il numero di file in ${AVATARS_DIR} è cambiato durante il reset." >&2
  exit 1
fi

if [[ "${final_sequence_last_value}" != "1" || "${final_sequence_is_called}" != "false" ]]; then
  echo "Errore: la sequence analyses_sequence_number_seq non è coerente con RESTART WITH 1." >&2
  exit 1
fi

echo
echo "Verifica finale"
echo "  COUNT(*) FROM analyses = ${final_analyses_count}"
echo "  Sequence analyses_sequence_number_seq: last_value=${final_sequence_last_value}, is_called=${final_sequence_is_called}"
echo "  File presenti in ${UPLOADS_DIR}: ${final_uploads_count}"
echo "  File presenti in ${AVATARS_DIR}: ${avatars_count_after}"
