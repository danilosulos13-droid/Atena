#!/usr/bin/env python3
"""Inicializa/migra o SQLite episódico da Atena de forma idempotente."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from core.episodic_memory import EpisodicMemoryError
from core.memory_store import MemoryStore

REQUIRED_TABLES = {
    "schema_migrations",
    "episodes",
    "provenance",
    "evidence_links",
    "research_intents",
    "source_health",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("atena_evolution/memory.sqlite3"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    db = args.db.resolve()
    db.parent.mkdir(parents=True, exist_ok=True)

    before: set[str] = set()
    if db.exists():
        with sqlite3.connect(db) as connection:
            before = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

    if args.check_only and "episodes" not in before:
        result = {"ok": False, "db": str(db), "reason": "episodes ausente", "tables_before": sorted(before)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        with MemoryStore(db) as store:
            tables = {
                row[0]
                for row in store.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = sorted(REQUIRED_TABLES - tables)
            if missing:
                raise RuntimeError(f"tabelas obrigatórias ausentes: {', '.join(missing)}")
            last_hash = store.verify_integrity()
            episode_count = store.count()
    except (EpisodicMemoryError, sqlite3.Error, RuntimeError, ValueError) as exc:
        result = {"ok": False, "db": str(db), "error": f"{type(exc).__name__}: {exc}"}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    result = {
        "ok": True,
        "db": str(db),
        "created_or_migrated": sorted(REQUIRED_TABLES - before),
        "tables": sorted(tables),
        "episode_count": episode_count,
        "integrity": "ok",
        "last_hash": last_hash,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
