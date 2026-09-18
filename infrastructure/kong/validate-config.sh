#!/bin/sh
set -eu

# Validazione statica della configurazione Kong.
# Lo script non avvia il gateway applicativo: rende il template, controlla che
# siano presenti service/upstream/target attesi e usa `kong config parse` per
# verificare che la configurazione declarative sia sintatticamente valida.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
KONG_IMAGE="${KONG_IMAGE:-kong:3.8.0}"
RENDERED_CONFIG="$(mktemp)"
trap 'rm -f "$RENDERED_CONFIG"' EXIT

sh "$SCRIPT_DIR/render-config.sh" "$SCRIPT_DIR/kong.template.yaml" "$RENDERED_CONFIG"

grep -q "name: analysis-api-service" "$RENDERED_CONFIG"
grep -q "name: analysis-api-upstream" "$RENDERED_CONFIG"
grep -q "target: analysis-api-1:8000" "$RENDERED_CONFIG"
grep -q "target: analysis-api-2:8000" "$RENDERED_CONFIG"
grep -q "name: rate-limiting" "$RENDERED_CONFIG"
grep -q "name: request-size-limiting" "$RENDERED_CONFIG"
grep -q "name: correlation-id" "$RENDERED_CONFIG"
grep -q "name: prometheus" "$RENDERED_CONFIG"
grep -q "http://localhost:8080" "$RENDERED_CONFIG"
grep -q "http://localhost:5173" "$RENDERED_CONFIG"
grep -q "127.0.0.1:8001:8001" "$REPO_ROOT/infrastructure/compose/compose.yaml"
# Questo controllo Python impedisce che le repliche API vengano esposte
# accidentalmente sul Mac bypassando il gateway.
python3 - <<'PY' "$REPO_ROOT/infrastructure/compose/compose.yaml"
from pathlib import Path
import sys

compose_path = Path(sys.argv[1])
text = compose_path.read_text()

for service_name in ("analysis-api-1", "analysis-api-2"):
    marker = f"\n  {service_name}:\n"
    start = text.find(marker)
    if start == -1:
        raise SystemExit(f"Missing service block: {service_name}")
    start += 1
    end = text.find("\n  ", start + len(marker))
    if end == -1:
        end = len(text)
    block = text[start:end]
    if "\n    ports:" in block:
        raise SystemExit(f"Direct host port exposure detected for {service_name}")
PY

# La validazione avviene nell'immagine ufficiale Kong per usare lo stesso parser del runtime reale.
docker run --rm \
  -e KONG_DATABASE=off \
  -e KONG_RATE_LIMIT_GET_PER_MINUTE="${KONG_RATE_LIMIT_GET_PER_MINUTE:-600}" \
  -e KONG_RATE_LIMIT_ME_GET_PER_MINUTE="${KONG_RATE_LIMIT_ME_GET_PER_MINUTE:-240}" \
  -e KONG_RATE_LIMIT_ME_WRITE_PER_MINUTE="${KONG_RATE_LIMIT_ME_WRITE_PER_MINUTE:-60}" \
  -e KONG_RATE_LIMIT_POST_PER_MINUTE="${KONG_RATE_LIMIT_POST_PER_MINUTE:-30}" \
  -e KONG_RATE_LIMIT_DELETE_PER_MINUTE="${KONG_RATE_LIMIT_DELETE_PER_MINUTE:-10}" \
  -e KONG_MAX_REQUEST_SIZE_MB="${KONG_MAX_REQUEST_SIZE_MB:-256}" \
  -e KONG_CORS_ALLOWED_ORIGINS="${KONG_CORS_ALLOWED_ORIGINS:-http://localhost:8080,http://localhost:5173}" \
  -v "$REPO_ROOT/infrastructure/kong:/opt/kong/securescan:ro" \
  "$KONG_IMAGE" \
  /bin/sh -c "sh /opt/kong/securescan/render-config.sh /opt/kong/securescan/kong.template.yaml /tmp/kong/kong.yaml && kong config parse /tmp/kong/kong.yaml"
