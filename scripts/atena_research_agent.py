#!/usr/bin/env python3
"""CLI do agente de pesquisa multiassunto da Atena."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from core.knowledge_base import KnowledgeBase
from core.research_agent import run_research

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "atena_evolution" / "memory.sqlite3"

def main() -> int:
    ap = argparse.ArgumentParser(description="Atena Research Agent")
    ap.add_argument("question")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    with KnowledgeBase(args.db) as kb:
        result = run_research(args.question, args.topic, kb=kb)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Tópico: {result['plan']['topic']}")
        print(result["summary"])
        for i, source in enumerate(result["sources"], 1):
            mark = "PRIMÁRIA" if source["primary"] else "secundária"
            print(f"{i:02d}. [{mark}] {source['title']} — {source['url']}")
        if result["conflicts"]:
            print("ATENÇÃO: existem possíveis conflitos; revisar fontes antes de concluir.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
