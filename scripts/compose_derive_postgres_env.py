#!/usr/bin/env python3
"""
Genera un .env auxiliar con POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB listos para
docker compose --env-file (interpolación en docker-compose.yml).

Fusiona valores explícitos del .env principal con los de DATABASE_URL cuando falten.

Uso: python3 compose_derive_postgres_env.py <entrada.env> <salida.env>
Salida: siempre las 3 claves (salvo error). Exit 1 si no hay contraseña en ninguna fuente.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lstrip("\ufeff")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def format_env_value(val: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:@%+-]+", val or ""):
        return val
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: compose_derive_postgres_env.py <entrada.env> <salida.env>", file=sys.stderr)
        return 2

    env_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    if not env_path.is_file():
        print(f"No existe: {env_path}", file=sys.stderr)
        return 2

    env = parse_dotenv(env_path)
    dburl = (env.get("DATABASE_URL") or "").strip()

    parsed = urlparse(dburl) if dburl else None
    url_user = unquote(parsed.username or "") if parsed else ""
    url_pass = unquote(parsed.password or "") if parsed else ""
    url_db = (parsed.path or "").lstrip("/") if parsed else ""
    if parsed and not url_db and parsed.path == "/":
        url_db = ""

    merged_user = (env.get("POSTGRES_USER") or "").strip() or url_user or "mepdetect"
    merged_pass = (env.get("POSTGRES_PASSWORD") or "").strip() or url_pass
    merged_db = (env.get("POSTGRES_DB") or "").strip() or url_db or "mepdetect"

    if not merged_pass:
        print(
            "Falta POSTGRES_PASSWORD o una contraseña en DATABASE_URL "
            f"(archivo: {env_path}).",
            file=sys.stderr,
        )
        return 1

    lines = [
        f"POSTGRES_USER={format_env_value(merged_user)}",
        f"POSTGRES_PASSWORD={format_env_value(merged_pass)}",
        f"POSTGRES_DB={format_env_value(merged_db)}",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
