"""Catálogo central e estado operacional das fontes monitoradas pela Atena.

O módulo é deliberadamente independente de HTTP e Telegram: os coletores informam
os resultados e este componente calcula estados, histórico e recomendações de
fallback. O SQLite usa WAL e operações idempotentes para permitir uso simultâneo
por workflows diferentes.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path("atena_evolution/memory.sqlite3")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    category: str
    url: str
    priority: int = 50
    expected_interval_minutes: int = 180
    enabled: bool = True


DEFAULT_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("steam", "games", "https://store.steampowered.com/search/?specials=1&cc=br&l=portuguese", 90, 30),
    SourceSpec("epic", "games", "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions", 90, 60),
    SourceSpec("gog", "games", "https://www.gog.com/en/games?discounted=true", 70, 180),
    SourceSpec("nuuvem", "games", "https://www.nuuvem.com/br-pt/promo/ofertas-nuuvem", 70, 180),
    SourceSpec("humble", "games", "https://www.humblebundle.com/store", 70, 180),
    SourceSpec("santos_fc_oficial", "news", "https://www.santosfc.com.br/feed/", 95, 180),
    SourceSpec("ge", "news", "https://ge.globo.com/rss/ge/", 90, 180),
    SourceSpec("agencia_brasil", "news", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml", 90, 180),
    SourceSpec("tecnoblog", "news", "https://tecnoblog.net/feed/", 80, 180),
    SourceSpec("olhar_digital", "news", "https://olhardigital.com.br/feed/", 80, 180),
)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = str(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


class MonitoringHealth:
    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = str(db_path)
        self.connection = _connect(db_path)
        self.ensure_schema()
        self.register_catalog(DEFAULT_SOURCES)

    def __enter__(self) -> "MonitoringHealth":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def ensure_schema(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_sources (
                    source_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    url TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 50,
                    expected_interval_minutes INTEGER NOT NULL DEFAULT 180,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS monitoring_source_checks (
                    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    latency_ms REAL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id)
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_checks_source_time
                    ON monitoring_source_checks(source_id, checked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_monitoring_sources_category
                    ON monitoring_sources(category, enabled);
                """
            )

    def register_catalog(self, sources: Iterable[SourceSpec]) -> None:
        stamp = utc_now()
        with self.connection:
            for source in sources:
                self.connection.execute(
                    """INSERT INTO monitoring_sources
                    (source_id, category, url, priority, expected_interval_minutes, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET category=excluded.category,
                    url=excluded.url, priority=excluded.priority,
                    expected_interval_minutes=excluded.expected_interval_minutes,
                    enabled=excluded.enabled, updated_at=excluded.updated_at""",
                    (source.source_id, source.category, source.url, source.priority,
                     source.expected_interval_minutes, int(source.enabled), stamp, stamp),
                )

    def record_check(
        self,
        source_id: str,
        *,
        status: str,
        http_status: int | None = None,
        latency_ms: float | None = None,
        item_count: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        checked_at: str | None = None,
    ) -> int:
        allowed = {"healthy", "degraded", "blocked", "stale", "failed"}
        if status not in allowed:
            raise ValueError(f"status inválido: {status}")
        stamp = checked_at or utc_now()
        with self.connection:
            exists = self.connection.execute("SELECT 1 FROM monitoring_sources WHERE source_id=?", (source_id,)).fetchone()
            if exists is None:
                self.connection.execute(
                    """INSERT INTO monitoring_sources
                    (source_id, category, url, priority, expected_interval_minutes, enabled, created_at, updated_at)
                    VALUES (?, 'unknown', ?, 50, 180, 1, ?, ?)""",
                    (source_id, source_id, stamp, stamp),
                )
            cursor = self.connection.execute(
                """INSERT INTO monitoring_source_checks
                (source_id, checked_at, status, http_status, latency_ms, item_count,
                 error_type, error_message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_id, stamp, status, http_status, latency_ms, max(0, int(item_count)),
                 error_type, error_message, json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
            )
        return int(cursor.lastrowid)

    def source_health(self, source_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """SELECT s.*, c.checked_at, c.status, c.http_status, c.latency_ms,
            c.item_count, c.error_type, c.error_message, c.metadata_json
            FROM monitoring_sources s LEFT JOIN monitoring_source_checks c
            ON c.check_id=(SELECT check_id FROM monitoring_source_checks WHERE source_id=s.source_id ORDER BY checked_at DESC, check_id DESC LIMIT 1)
            WHERE s.source_id=?""", (source_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def all_health(self, *, category: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT source_id FROM monitoring_sources"
        clauses: list[str] = []
        args: list[Any] = []
        if category:
            clauses.append("category=?"); args.append(category)
        if enabled_only:
            clauses.append("enabled=1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY priority DESC, source_id"
        return [item for row in self.connection.execute(query, args) if (item := self.source_health(str(row[0]))) is not None]

    def summary(self) -> dict[str, Any]:
        sources = self.all_health()
        counts: dict[str, int] = {}
        for item in sources:
            status = item.get("status") or "unobserved"
            counts[status] = counts.get(status, 0) + 1
        checks = self.connection.execute("SELECT COUNT(*) FROM monitoring_source_checks").fetchone()[0]
        return {"generated_at": utc_now(), "total_sources": len(sources), "status_counts": counts,
                "checks_recorded": int(checks), "sources": sources}

    def fallback_sources(self, category: str, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
        excluded = set(exclude)
        return [item for item in self.all_health(category=category, enabled_only=True)
                if item["source_id"] not in excluded and item.get("status") not in {"blocked", "failed"}]


def main() -> int:
    parser = argparse.ArgumentParser(description="Mostra a saúde das fontes monitoradas pela Atena")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--category")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with MonitoringHealth(args.db) as health:
        payload = health.summary() if not args.category else {"sources": health.all_health(category=args.category)}
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
