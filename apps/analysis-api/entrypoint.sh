#!/bin/sh
set -e

# Questo script non corrisponde a una pagina del sito. Serve ad avviare il
# container API in modo coerente sia nella demo locale sia nei test.
#
# Le migrazioni opzionali all'avvio evitano che il backend dipenda da un
# passaggio manuale separato prima di rendere disponibili Cronologia,
# Dashboard, Profilo e le altre pagine che leggono da PostgreSQL.
if [ "${RUN_DB_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
fi

# Uvicorn resta il solo processo PID 1 così segnali e shutdown puliti vengono
# propagati correttamente anche al loop heartbeat della replica API.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
