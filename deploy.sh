#!/usr/bin/env bash
# Despliegue local o en servidor: levanta PostgreSQL, Redis, landing, user-api,
# detection-api y training-api desde la raíz del monorepo (un solo compose).
#
# Prerrequisitos:
#   - Docker con plugin "compose"
#   - Variables: mepdetect-user-api/.env (preferido) o .env en la raíz, o MEPDETECT_ENV_FILE
#   - Tras ./dcompose o deploy, ./.env queda fusionado (POSTGRES_* + resto) para `docker compose` sin WARN
#
# Puertos por defecto (host): landing 8090, detección 8091, training 8092, user-api 8093
#
# Sincronizar código con git antes de construir (estilo servidor compartido):
#   MEPDETECT_GIT_SYNC=1 ./deploy.sh
#   MEPDETECT_GIT_REF=origin/main   # opcional, por defecto origin/main
#
# Si existe docker-compose.prod.yml se fusiona después del base.
#
# Para cualquier subcomando de compose (ps, logs, down) con los mismos env que el build:
#   ./scripts/dcompose ps
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ "${MEPDETECT_GIT_SYNC:-0}" == "1" ]]; then
  REF="${MEPDETECT_GIT_REF:-origin/main}"
  git fetch origin && git reset --hard "$REF"
fi

chmod +x "$ROOT/scripts/dcompose" "$ROOT/dcompose" "$ROOT/scripts/sync-compose-root-dotenv.sh" 2>/dev/null || true
"$ROOT/scripts/dcompose" up -d --build

if [[ -n "${MEPDETECT_ENV_FILE:-}" ]]; then
  echo "Compose (fuente): $MEPDETECT_ENV_FILE"
elif [[ -f "$ROOT/mepdetect-user-api/.env" ]]; then
  echo "Compose (fuente): $ROOT/mepdetect-user-api/.env"
else
  echo "Compose (fuente): $ROOT/.env"
fi
echo "Compose (interpolación): $ROOT/.env (fusionado; gitignored)"
echo "Compose (postgres aux): $ROOT/.compose/postgres.env"

docker image prune -f >/dev/null || true
