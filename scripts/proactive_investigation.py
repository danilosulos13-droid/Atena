#!/usr/bin/env python3
"""Diagnóstico proativo read-only; nunca altera código ou dispositivos."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "atena_evolution" / "proposals"


def run(*args: str) -> str:
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main() -> int:
    status = run("git", "status", "--short")
    todos = run("git", "grep", "-n", "-I", "-E", "TODO|FIXME|XXX")
    proposal = {
        "type": "proactive_read_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "observations": {
            "working_tree_changes": len([line for line in status.splitlines() if line.strip()]),
            "maintenance_markers": len(todos.splitlines()),
        },
        "evidence": {"git_status": status.splitlines()[:100], "markers": todos.splitlines()[:100]},
        "insights": [
            "Revisar alterações locais antes de qualquer promoção automática.",
            "Priorizar testes de regressão para marcadores TODO/FIXME encontrados.",
            "Pesquisar fontes públicas recentes sobre visão, recuperação vetorial e segurança de agentes no próximo ciclo.",
        ],
        "risks": [
            "Nenhuma alteração de código, credencial ou dispositivo foi executada por este diagnóstico.",
            "Resultados externos devem ser verificados por fontes primárias antes de virar memória de treino.",
        ],
        "next_cycle": ["coletar fontes públicas", "avaliar testes", "propor mudanças para revisão humana"],
    }
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    output = PROPOSALS / f"proactive-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "proposal": str(output), "read_only": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
