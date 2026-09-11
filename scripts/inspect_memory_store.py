#!/usr/bin/env python3
"""Inspeção somente leitura do relatório de migração e do SQLite episódico."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from core.episodic_memory import EpisodicMemoryError, verify_hash_chain
from scripts.notify_telegram_learning import send as send_telegram

REQUIRED_TABLES = {
    "schema_migrations",
    "episodes",
    "provenance",
    "evidence_links",
    "research_intents",
    "source_health",
}


def load_report(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return {"ok": False, "error": f"relatório não encontrado: {path}"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"relatório inválido: {type(exc).__name__}: {exc}"}
    return value if isinstance(value, dict) else {"ok": False, "error": "relatório não é um objeto JSON"}


def inspect_database(path: Path, limit: int) -> dict:
    if not path.exists():
        return {"ok": False, "error": f"banco não encontrado: {path}"}

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            }
            counts = {}
            for table in sorted(REQUIRED_TABLES):
                if table in tables:
                    counts[table] = connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
            recent = []
            if "episodes" in tables:
                recent = [dict(row) for row in connection.execute(
                    "SELECT sequence, id, created_at, task_id, status, lifecycle_state "
                    "FROM episodes ORDER BY sequence DESC LIMIT ?", (limit,)
                )]
            return {
                "ok": REQUIRED_TABLES <= tables,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "tables": sorted(tables),
                "missing_tables": sorted(REQUIRED_TABLES - tables),
                "counts": counts,
                "recent_episodes": recent,
            }
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "path": str(path), "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("atena_evolution/memory.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("/tmp/atena-memory-migration.json"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--alert-on-failure",
        action="store_true",
        help="envia alerta Telegram somente quando o diagnóstico falhar",
    )
    parser.add_argument(
        "--allow-missing-alert",
        action="store_true",
        help="não falha novamente se as credenciais Telegram não existirem",
    )
    parser.add_argument(
        "--allow-missing-report",
        action="store_true",
        help="não considera erro a ausência do relatório de migração",
    )
    args = parser.parse_args()
    limit = max(1, min(args.limit, 50))

    report = load_report(args.report)
    if args.allow_missing_report and report and "relatório não encontrado" in str(report.get("error", "")):
        report = None
    database = inspect_database(args.db.resolve(), limit)
    integrity = {"ok": False, "status": "not_checked"}
    if database.get("ok"):
        try:
            # Abrir em modo read-only: o diagnóstico não cria tabelas nem grava WAL.
            with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as connection:
                records = [
                    json.loads(row[0])
                    for row in connection.execute(
                        "SELECT record_json FROM episodes ORDER BY sequence ASC"
                    )
                ]
            integrity = {"ok": True, "status": "ok", "last_hash": verify_hash_chain(records)}
        except (EpisodicMemoryError, sqlite3.Error, OSError) as exc:
            integrity = {"ok": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    result = {
        "ok": bool((report is None or report.get("ok") is True) and database.get("ok") and integrity.get("ok")),
        "migration_report": report,
        "database": database,
        "integrity": integrity,
    }
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {'OK' if result['ok'] else 'FALHA'}")
        print(f"banco: {database.get('path', args.db)}")
        print(f"tamanho: {database.get('size_bytes', 0)} bytes")
        print(f"tabelas: {', '.join(database.get('tables', [])) or 'nenhuma'}")
        print(f"tabelas ausentes: {', '.join(database.get('missing_tables', [])) or 'nenhuma'}")
        print(f"contagens: {database.get('counts', {})}")
        print(f"integridade: {integrity.get('status')}")
        print(f"hash final: {integrity.get('last_hash')}")
        if report:
            print(f"relatório migração: {'OK' if report.get('ok') else 'FALHA'}")
        print("episódios recentes:")
        for item in database.get("recent_episodes", []):
            print("  " + json.dumps(item, ensure_ascii=False))

    if args.alert_on_failure and not result["ok"]:
        import html
        import os

        token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            message = "Telegram não configurado para alertas de integridade SQLite."
            if args.allow_missing_alert:
                print(f"::warning::{message}", file=sys.stderr)
            else:
                print(message, file=sys.stderr)
                return 2
        else:
            error = result.get("integrity", {}).get("error") or result.get("database", {}).get("error") or "falha de schema/migração"
            alert = (
                "<b>ATENA — falha de integridade SQLite</b>\n"
                "A cadeia de hashes ou o schema episódico falhou.\n"
                f"<code>{html.escape(str(error))[:1200]}</code>"
            )
            try:
                send_telegram(token, chat_id, alert)
                print("Alerta de integridade enviado ao Telegram.", file=sys.stderr)
            except Exception as exc:
                print(f"Falha ao enviar alerta Telegram: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
