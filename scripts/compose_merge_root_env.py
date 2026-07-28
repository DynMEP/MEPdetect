#!/usr/bin/env python3
"""
Fusiona el .env principal con .compose/postgres.env en ./.env (raíz del repo).

Reglas para POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB:
  - Si en el principal el valor está ausente o solo espacios, usa el del derivado.
  - Si el principal tiene valor no vacío, se conserva.

El resto de claves vienen del principal (orden de aparición conservado en lo posible).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_dotenv(path: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Devuelve (mapa, orden como lista de (key, value)); última repetición de clave gana."""
    order: list[tuple[str, str]] = []
    index: dict[str, int] = {}
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
        if key in index:
            order[index[key]] = (key, val)
        else:
            index[key] = len(order)
            order.append((key, val))
    return dict(order), order


def format_env_value(val: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:@%+-]+", val or ""):
        return val
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Uso: compose_merge_root_env.py <principal.env> <postgres.env> <salida.env>",
            file=sys.stderr,
        )
        return 2
    primary_path = Path(sys.argv[1])
    derived_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    if not primary_path.is_file() or not derived_path.is_file():
        print("Falta archivo de entrada.", file=sys.stderr)
        return 2

    primary_map, order = parse_dotenv(primary_path)
    derived_map, _ = parse_dotenv(derived_path)

    pg_keys = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    for k in pg_keys:
        cur = (primary_map.get(k) or "").strip()
        if not cur and k in derived_map:
            primary_map[k] = derived_map[k]
            replaced = False
            for i, (ok, _) in enumerate(order):
                if ok == k:
                    order[i] = (k, derived_map[k])
                    replaced = True
                    break
            if not replaced:
                order.append((k, derived_map[k]))

    lines_out: list[str] = [
        "# Fusionado por scripts/compose_merge_root_env.py (no edites a mano; se regenera).",
        "# Edita mepdetect-user-api/.env y ejecuta ./dcompose o ./deploy.sh",
        "",
    ]
    for key, val in order:
        lines_out.append(f"{key}={format_env_value(val)}")
    out_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
