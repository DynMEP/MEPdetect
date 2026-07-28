#!/usr/bin/env bash
# Regenera .compose/postgres.env y (por defecto) ./.env fusionado, sin ejecutar docker compose.
# Útil tras git pull si solo quieres que `docker compose logs` deje de mostrar WARN.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${MEPDETECT_ENV_FILE:-}"
if [[ -z "$ENV_FILE" ]]; then
  if [[ -f "$ROOT/mepdetect-user-api/.env" ]]; then
    ENV_FILE="$ROOT/mepdetect-user-api/.env"
  elif [[ -f "$ROOT/.env" ]]; then
    ENV_FILE="$ROOT/.env"
  else
    echo "No se encontró mepdetect-user-api/.env ni .env en $ROOT" >&2
    exit 1
  fi
fi

mkdir -p "$ROOT/.compose"
DERIVED="$ROOT/.compose/postgres.env"
python3 "$ROOT/scripts/compose_derive_postgres_env.py" "$ENV_FILE" "$DERIVED"

if [[ "${MEPDETECT_SYNC_ROOT_DOTENV:-1}" != "0" ]]; then
  MERGE_TMP="$ROOT/.env.__merge.$$"
  python3 "$ROOT/scripts/compose_merge_root_env.py" "$ENV_FILE" "$DERIVED" "$MERGE_TMP"
  mv "$MERGE_TMP" "$ROOT/.env"
  echo "OK: $ROOT/.env y $DERIVED"
else
  echo "OK: $DERIVED (MEPDETECT_SYNC_ROOT_DOTENV=0, no se tocó ./.env)"
fi
