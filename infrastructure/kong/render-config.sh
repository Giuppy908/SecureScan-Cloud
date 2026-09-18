#!/bin/sh
set -eu

# Questo script trasforma il template Kong in una configurazione finale pronta
# per il parsing. Esiste per evitare duplicazione: i placeholder restano nel
# file versionato, mentre i valori concreti arrivano dall'environment locale o
# production.

TEMPLATE_PATH="${1:-/opt/kong/securescan/kong.template.yaml}"
OUTPUT_PATH="${2:-/tmp/kong/kong.yaml}"

mkdir -p "$(dirname "$OUTPUT_PATH")"
cp "$TEMPLATE_PATH" "$OUTPUT_PATH"

replace_placeholder() {
  # Sostituzione semplice dei placeholder numerici o testuali del template.
  placeholder="$1"
  value="$2"
  tmp_file="$(mktemp)"
  sed "s|${placeholder}|${value}|g" "$OUTPUT_PATH" > "$tmp_file"
  mv "$tmp_file" "$OUTPUT_PATH"
}

render_cors_origins() {
  # Le origin CORS vengono espanse su più righe YAML per mantenere leggibile il
  # template e permettere ambienti diversi senza riscrivere la struttura.
  origins_csv="${KONG_CORS_ALLOWED_ORIGINS:-http://localhost:8080,http://localhost:5173}"
  replacement_file="$(mktemp)"
  trap 'rm -f "$replacement_file"' EXIT HUP INT TERM
  old_ifs="$IFS"
  IFS=','
  for origin in $origins_csv; do
    trimmed_origin="$(printf '%s' "$origin" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -n "$trimmed_origin" ] || continue
    printf '            - %s\n' "$trimmed_origin" >> "$replacement_file"
  done
  IFS="$old_ifs"

  [ -s "$replacement_file" ] || {
    echo "KONG_CORS_ALLOWED_ORIGINS must contain at least one origin." >&2
    exit 1
  }

  tmp_file="$(mktemp)"
  awk -v replacement_file="$replacement_file" '
    index($0, "__KONG_CORS_ORIGINS__") {
      while ((getline line < replacement_file) > 0) {
        print line
      }
      close(replacement_file)
      next
    }
    { print }
  ' "$OUTPUT_PATH" > "$tmp_file"
  mv "$tmp_file" "$OUTPUT_PATH"
  rm -f "$replacement_file"
  trap - EXIT HUP INT TERM
}

replace_placeholder "__KONG_RATE_LIMIT_GET_PER_MINUTE__" "${KONG_RATE_LIMIT_GET_PER_MINUTE:-600}"
replace_placeholder "__KONG_RATE_LIMIT_ME_GET_PER_MINUTE__" "${KONG_RATE_LIMIT_ME_GET_PER_MINUTE:-240}"
replace_placeholder "__KONG_RATE_LIMIT_ME_WRITE_PER_MINUTE__" "${KONG_RATE_LIMIT_ME_WRITE_PER_MINUTE:-60}"
replace_placeholder "__KONG_RATE_LIMIT_POST_PER_MINUTE__" "${KONG_RATE_LIMIT_POST_PER_MINUTE:-30}"
replace_placeholder "__KONG_RATE_LIMIT_DELETE_PER_MINUTE__" "${KONG_RATE_LIMIT_DELETE_PER_MINUTE:-10}"
replace_placeholder "__KONG_MAX_REQUEST_SIZE_MB__" "${KONG_MAX_REQUEST_SIZE_MB:-256}"
render_cors_origins
