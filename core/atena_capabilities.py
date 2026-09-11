#!/usr/bin/env python3
"""Exibe o catálogo estático de capacidades disponíveis da Atena."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.capability_registry import catalog_dicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catálogo de capacidades da Atena")
    parser.add_argument("--area", choices=["root", "core", "modules", "scripts", "examples", "api", "dashboard", "consciousness", "plugins", "skills", "setup"])
    parser.add_argument("--runnable", action="store_true", help="mostrar somente módulos com ponto de entrada")
    args = parser.parse_args(argv)
    items = catalog_dicts()
    if args.area:
        items = [item for item in items if item["area"] == args.area]
    if args.runnable:
        items = [item for item in items if item["entrypoints"]]
    print(json.dumps({"root": str(ROOT), "count": len(items), "capabilities": items}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
