#!/usr/bin/env bash
# Despliegue local o en servidor: levanta PostgreSQL, Redis, landing, user-api,
# detection-api y training-api desde la raíz del monorepo (un solo compose).
#
# Este es el ÚNICO punto de entrada. Comprueba el entorno, construye, arranca y
# no termina hasta que cada servicio responde a su healthcheck; si alguno no
# llega, imprime sus logs y sale con error en vez de dar un éxito falso.
# Los deploy.sh / quick-deploy.sh dentro de mepdetect-user-api/ son heredados
# (docker run suelto) y no deben usarse: no levantan el stack completo.
#
# Prerrequisitos:
#   - Docker con plugin "compose"
#   - python3 en el host (deriva POSTGRES_* para la interpolación de compose)
#   - Variables: mepdetect-user-api/.env (preferido) o .env en la raíz, o MEPDETECT_ENV_FILE
#   - Tras ./dcompose o deploy, ./.env queda fusionado (POSTGRES_* + resto) para `docker compose` sin WARN
#
# MEPDETECT_HEALTH_TIMEOUT=300  segundos a esperar por los healthchecks
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

# --- Preflight -------------------------------------------------------------
# Comprobar el entorno antes de construir: un fallo aquí cuesta segundos, el
# mismo fallo a mitad del build cuesta minutos y deja imágenes a medias.

command -v docker >/dev/null || { echo "ERROR: docker no está instalado." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || {
  echo "ERROR: falta el plugin 'compose' de docker (docker compose)." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "ERROR: el daemon de docker no responde (¿permisos? ¿está arrancado?)." >&2
  exit 1
}
command -v python3 >/dev/null || {
  echo "ERROR: se requiere python3 (scripts/compose_derive_postgres_env.py)." >&2
  exit 1
}

chmod +x "$ROOT/scripts/dcompose" "$ROOT/dcompose" "$ROOT/scripts/sync-compose-root-dotenv.sh" 2>/dev/null || true

if [[ -n "${MEPDETECT_ENV_FILE:-}" ]]; then
  ENV_SOURCE="$MEPDETECT_ENV_FILE"
elif [[ -f "$ROOT/mepdetect-user-api/.env" ]]; then
  ENV_SOURCE="$ROOT/mepdetect-user-api/.env"
else
  ENV_SOURCE="$ROOT/.env"
fi

echo "Compose (fuente): $ENV_SOURCE"
echo "Compose (interpolación): $ROOT/.env (fusionado; gitignored)"
echo "Compose (postgres aux): $ROOT/.compose/postgres.env"
echo

# --- Arranque --------------------------------------------------------------
# dcompose deriva POSTGRES_* y aborta si no hay contraseña en ninguna fuente,
# que es de donde compose construye DATABASE_URL para los tres servicios.

"$ROOT/scripts/dcompose" up -d --build

# --- Verificación ----------------------------------------------------------
# `up -d` vuelve en cuanto los contenedores arrancan, no cuando el servicio de
# dentro responde. Sin esperar aquí, un contenedor en bucle de reinicio deja
# este script terminando en éxito y el fallo se descubre en el navegador.

TIMEOUT="${MEPDETECT_HEALTH_TIMEOUT:-300}"
mapfile -t CONTAINERS < <("$ROOT/scripts/dcompose" ps -q)

if [[ ${#CONTAINERS[@]} -eq 0 ]]; then
  echo "ERROR: compose no dejó ningún contenedor en marcha." >&2
  exit 1
fi

echo "Esperando a que ${#CONTAINERS[@]} servicios estén sanos (máx ${TIMEOUT}s)..."

state_of() {  # -> "ok" | "wait" | "fail"
  local cid="$1" status health
  status=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)
  case "$status" in
    running)
      case "$health" in
        healthy|none) echo ok ;;
        starting)     echo wait ;;
        *)            echo fail ;;
      esac
      ;;
    created|restarting) echo wait ;;
    *)                  echo fail ;;
  esac
}

name_of() { docker inspect -f '{{.Name}}' "$1" 2>/dev/null | sed 's#^/##'; }

DEADLINE=$(( SECONDS + TIMEOUT ))
FAILED=()

while :; do
  PENDING=(); FAILED=()
  for cid in "${CONTAINERS[@]}"; do
    case "$(state_of "$cid")" in
      wait) PENDING+=("$cid") ;;
      fail) FAILED+=("$cid") ;;
    esac
  done

  # Un contenedor que se reinicia se ve "wait" un instante y "fail" al
  # siguiente, así que sólo se decide cuando ya no queda nada por esperar.
  if [[ ${#PENDING[@]} -eq 0 ]]; then break; fi
  if (( SECONDS >= DEADLINE )); then FAILED+=("${PENDING[@]}"); break; fi
  sleep 3
done

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo >&2
  echo "ERROR: ${#FAILED[@]} servicio(s) no llegaron a estar sanos:" >&2
  for cid in "${FAILED[@]}"; do
    echo "  --- $(name_of "$cid") ---" >&2
    docker logs --tail 25 "$cid" 2>&1 | sed 's/^/      /' >&2
  done
  echo >&2
  echo "Logs completos: ./scripts/dcompose logs <servicio>" >&2
  exit 1
fi

docker image prune -f >/dev/null || true

LANDING="${LANDING_PORT:-8090}"
echo
echo "Todo en marcha:"
echo "  Landing      http://localhost:${LANDING}"
echo "  Detección    http://localhost:${DETECTION_API_PORT:-8091}/api/docs"
echo "  Training     http://localhost:${TRAINING_API_PORT:-8092}/api/docs"
echo "  Usuarios     http://localhost:${USER_API_PORT:-8093}/api/docs"
echo
echo "Estado: ./scripts/dcompose ps    Logs: ./scripts/dcompose logs -f <servicio>"
