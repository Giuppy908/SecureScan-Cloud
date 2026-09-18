#!/usr/bin/env bash
set -euo pipefail

# Avvio della variante demo di SecureScan Cloud.
# Usa il Compose base piu` l'overlay demo per predisporre un ambiente locale
# pensato per presentazioni e prove manuali, mantenendo separata la logica
# destinata alla futura production.
#
# Anche questo script non implementa direttamente una pagina web, ma rende
# disponibili i servizi che il browser usera` poi tramite frontend, Kong,
# Keycloak e i container applicativi.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

docker compose \
  -f infrastructure/compose/compose.yaml \
  -f infrastructure/compose/compose.demo.yaml \
  up -d
