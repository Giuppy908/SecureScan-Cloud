#!/usr/bin/env bash
set -euo pipefail

# Avvio rapido dello stack locale canonico di SecureScan Cloud.
# Questo script e` pensato per la demo e per lo sviluppo quotidiano:
# richiama il Compose base gia` validato senza applicare overlay production.
#
# Non corrisponde a una pagina del sito, ma abilita indirettamente tutte le
# pagine dell'applicazione locale: Dashboard, Nuova analisi, Cronologia,
# Dettaglio analisi, Profilo, Amministrazione e osservabilita`.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

docker compose \
  -f infrastructure/compose/compose.yaml \
  up -d
