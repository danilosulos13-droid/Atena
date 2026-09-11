#!/usr/bin/env python3
"""Build and validate the persistent SQLite FTS5 index for ATENA memory."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def migrate(db_path: Path, rebuild: bool = False) -> dict[str, int | str]:
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                content='memory',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )"""
        )
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS memory_fts_ai
            AFTER INSERT ON memory BEGIN
                INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fts_au
            AFTER UPDATE OF content ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fts_ad
            AFTER DELETE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
            END;
            """
        )
        if rebuild:
            conn.execute("INSERT INTO memory_fts(memory_fts) VALUES ('rebuild')")
        conn.commit()
        memory_count = conn.execute("SELECT count(*) FROM memory").fetchone()[0]
        indexed_count = conn.execute(
            "SELECT count(*) FROM memory_fts"
        ).fetchone()[0]
        return {
            "database": str(db_path),
            "memory_rows": memory_count,
            "fts_rows": indexed_count,
            "consistent": int(memory_count == indexed_count),
        }
    finally:
        conn.close()


def migrate_separate(db_path: Path, lexical_db: Path, batch_size: int = 5000) -> dict[str, int | str]:
    """Constrói um FTS5 standalone; consultas abrem esse arquivo em read-only."""
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    target = sqlite3.connect(lexical_db, timeout=60)
    target.execute("PRAGMA journal_mode=WAL")
    target.execute("PRAGMA busy_timeout=60000")
    try:
        target.execute("DROP TABLE IF EXISTS memory_fts")
        target.execute("""CREATE VIRTUAL TABLE memory_fts USING fts5(
            content,
            memory_id UNINDEXED,
            tenant_id UNINDEXED,
            classification UNINDEXED,
            tags_json UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )""")
        cursor = source.execute("SELECT id, tenant_id, content, classification, tags_json FROM memory ORDER BY id")
        total = 0
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            target.executemany(
                "INSERT INTO memory_fts(content, memory_id, tenant_id, classification, tags_json) VALUES (?, ?, ?, ?, ?)",
                [(row[2], row[0], row[1], row[3], row[4]) for row in rows],
            )
            target.commit()
            total += len(rows)
        return {"database": str(db_path), "lexical_database": str(lexical_db), "memory_rows": total, "fts_rows": total, "consistent": 1}
    finally:
        source.close()
        target.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--output", type=Path, help="Arquivo SQLite FTS5 separado")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.output:
        result = migrate_separate(args.db, args.output, args.batch_size)
    else:
        result = migrate(args.db, args.rebuild)
    print(json.dumps(result, ensure_ascii=False) if args.json else result)
    if not result["consistent"]:
        raise SystemExit("FTS5 and memory row counts differ")


if __name__ == "__main__":
    main()
