#!/usr/bin/env bash
set -euo pipefail

# Preflight fail-fast per la configurazione production.
# Questo script non avvia servizi e non modifica file: controlla soltanto che
# il futuro `.env.production` non contenga credenziali mancanti o placeholder
# demo incompatibili con un deployment Internet-facing.
#
# E` collegato soprattutto alla milestone di deployment, non a una pagina del
# sito. Protegge pero` indirettamente tutti i flow pubblici, perche` impedisce
# di avviare Keycloak, backend o Grafana con secret deboli o incoerenti.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.production"
ERRORS=()

if [[ $# -gt 0 ]]; then
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env-file)
        if [[ $# -lt 2 ]]; then
          echo "Uso: $0 [--env-file /percorso/file.env]" >&2
          exit 1
        fi
        ENV_FILE="$2"
        shift 2
        ;;
      *)
        echo "Argomento non riconosciuto: $1" >&2
        echo "Uso: $0 [--env-file /percorso/file.env]" >&2
        exit 1
        ;;
    esac
  done
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "File environment non trovato: ${ENV_FILE}" >&2
  exit 1
fi

trim() {
  # Gli .env vengono letti come testo semplice: prima della validazione
  # normalizziamo gli spazi per evitare falsi positivi dovuti a formattazione.
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

strip_quotes() {
  # Permette di accettare valori scritti con o senza virgolette nel file env,
  # mantenendo la validazione indipendente dallo stile usato.
  local value="$1"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value#\'}"
    value="${value%\'}"
  fi
  printf '%s' "${value}"
}

get_file_value() {
  # Cerca una variabile direttamente nel file env quando non e` gia` stata
  # esportata nell'ambiente della shell corrente.
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi
  strip_quotes "$(trim "${line#*=}")"
}

get_value() {
  # Priorita`: shell corrente, poi file env. Questo consente override temporanei
  # nei test senza riscrivere il file `.env.production`.
  local key="$1"
  if [[ -n "${!key+x}" ]]; then
    printf '%s' "${!key}"
    return 0
  fi
  get_file_value "${key}"
}

add_error() {
  ERRORS+=("$1")
}

is_template_placeholder() {
  # I placeholder tra parentesi angolari documentano cosa va fornito, ma in
  # production non devono mai restare valori effettivi.
  local value="$1"
  case "${value}" in
    \<*\>)
      return 0
      ;;
  esac
  return 1
}

is_demo_placeholder() {
  # Blocca i valori noti usati nella demo locale per evitare che finiscano in
  # un ambiente pubblico con autenticazione reale.
  local value="$1"
  case "${value}" in
    change-me|change-me-*|ChangeMe-Analyst-123!|ChangeMe-Admin-123!|change_me|changeme)
      return 0
      ;;
  esac
  return 1
}

require_value() {
  # Usato per configurazioni che devono esistere, anche se non sono "secret"
  # in senso stretto, come username bootstrap o client id.
  local key="$1"
  local label="${2:-$1}"
  local value
  value="$(get_value "${key}" || true)"
  if [[ -z "${value}" ]]; then
    add_error "${label} mancante o vuota"
    return
  fi
  if is_template_placeholder "${value}"; then
    add_error "${label} usa ancora un placeholder template"
  fi
}

require_secret() {
  # Usato per credenziali e token sensibili: oltre alla presenza, rifiuta
  # placeholder demo, template e stringhe `change-me`.
  local key="$1"
  local label="${2:-$1}"
  local value
  value="$(get_value "${key}" || true)"
  if [[ -z "${value}" ]]; then
    add_error "${label} mancante o vuota"
    return
  fi
  if is_template_placeholder "${value}" || is_demo_placeholder "${value}" || [[ "${value}" == *"change-me"* ]]; then
    add_error "${label} usa ancora un placeholder demo/template non valido"
  fi
}

require_true() {
  # Alcune protezioni devono essere obbligatoriamente attive in production,
  # per esempio la disabilitazione degli utenti demo locali.
  local key="$1"
  local label="${2:-$1}"
  local value
  value="$(get_value "${key}" || true)"
  if [[ "$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')" != "true" ]]; then
    add_error "${label} deve essere impostata a true in production"
  fi
}

require_value "KEYCLOAK_ADMIN_USERNAME"
require_secret "POSTGRES_PASSWORD"
require_secret "DATABASE_URL"
require_secret "KEYCLOAK_ADMIN_PASSWORD"
require_secret "KEYCLOAK_ADMIN_CLIENT_SECRET"
require_value "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID"
require_secret "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET"
require_value "KEYCLOAK_DB_NAME"
require_value "KEYCLOAK_DB_USERNAME"
require_secret "KEYCLOAK_DB_PASSWORD"
require_secret "GRAFANA_ADMIN_PASSWORD"
require_true "KEYCLOAK_DISABLE_DEMO_USERS"
require_value "SECURESCAN_PUBLIC_FRONTEND_URL"
require_value "SECURESCAN_PUBLIC_KEYCLOAK_URL"
require_value "VITE_ANALYSIS_API_URL"
require_value "VITE_KEYCLOAK_URL"
require_value "KEYCLOAK_PUBLIC_HOSTNAME"
require_value "KEYCLOAK_ISSUER"

postgres_db_value="$(get_value "POSTGRES_DB" || true)"
postgres_user_value="$(get_value "POSTGRES_USER" || true)"
keycloak_db_name_value="$(get_value "KEYCLOAK_DB_NAME" || true)"
keycloak_db_username_value="$(get_value "KEYCLOAK_DB_USERNAME" || true)"

if [[ -n "${postgres_db_value}" && -n "${keycloak_db_name_value}" && "${postgres_db_value}" == "${keycloak_db_name_value}" ]]; then
  add_error "KEYCLOAK_DB_NAME deve essere distinto da POSTGRES_DB in production"
fi

if [[ -n "${postgres_user_value}" && -n "${keycloak_db_username_value}" && "${postgres_user_value}" == "${keycloak_db_username_value}" ]]; then
  add_error "KEYCLOAK_DB_USERNAME deve essere distinto da POSTGRES_USER in production"
fi

smtp_auth_value="$(get_value "KEYCLOAK_SMTP_AUTH" || true)"
if [[ "$(printf '%s' "${smtp_auth_value}" | tr '[:upper:]' '[:lower:]')" == "true" ]]; then
  require_value "KEYCLOAK_SMTP_USER"
  require_secret "KEYCLOAK_SMTP_PASSWORD"
fi

if [[ "${#ERRORS[@]}" -gt 0 ]]; then
  echo "Validazione environment production fallita:" >&2
  for error in "${ERRORS[@]}"; do
    echo " - ${error}" >&2
  done
  exit 1
fi

echo "Environment production valido."
