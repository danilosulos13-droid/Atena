#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instalador unificado e auditável da ATENA.

Uso:
  python setup/install.py                 # core + dev
  python setup/install.py --autonomous    # + stack de aprendizagem LoRA
  python setup/install.py --all           # todos os grupos, incluindo ML pesado

A instalação é delegada ao instalador auditável para manter um único inventário
oficial de dependências e produzir relatório em atena_evolution/dependency_installs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_dependency_installer import run_dependency_install


def main() -> int:
    parser = argparse.ArgumentParser(description="Instalador unificado da ATENA")
    parser.add_argument("--all", action="store_true", help="Instala core, dev, ML/LLM e aprendizagem autônoma.")
    parser.add_argument("--autonomous", action="store_true", help="Inclui dependências de aprendizagem autônoma/LoRA.")
    parser.add_argument("--apply", action="store_true", help="Executa a instalação. Sem isso, apenas gera plano.")
    parser.add_argument("--upgrade-pip", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    groups = ["core", "dev"]
    if args.all:
        groups = ["core", "dev", "ultimate", "autonomous"]
    elif args.autonomous:
        groups.append("autonomous")

    payload = run_dependency_install(groups, apply=args.apply, upgrade_pip=args.upgrade_pip)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ATENA: {payload['status']} | applied={payload['applied']}")
        print("Grupos:", ", ".join(groups))
        print("Relatório:", payload["report_path"])
    return int(payload.get("returncode", 0))


if __name__ == "__main__":
    raise SystemExit(main())
