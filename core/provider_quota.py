"""Controle local de uso, quotas e cooldowns dos provedores LLM."""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class QuotaLimit:
    requests: int
    tokens: int
    usd: float


def _int_env(name: str, default: int = 0) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


class QuotaLedger:
    """Ledger conservador: zero significa sem limite local configurado."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("ATENA_PROVIDER_QUOTA_DB", "atena_evolution/provider_quota.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provider_usage (
                    provider TEXT NOT NULL,
                    day TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    usd REAL NOT NULL DEFAULT 0,
                    cooldown_until REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    PRIMARY KEY(provider, day)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _day() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _env_prefix(provider: str) -> str:
        return "ATENA_" + provider.upper()

    def limit(self, provider: str) -> QuotaLimit:
        prefix = self._env_prefix(provider)
        return QuotaLimit(
            requests=_int_env(prefix + "_DAILY_REQUESTS"),
            tokens=_int_env(prefix + "_DAILY_TOKENS"),
            usd=_float_env(prefix + "_DAILY_USD"),
        )

    def _row(self, conn: sqlite3.Connection, provider: str) -> tuple[int, int, float, float] | None:
        row = conn.execute(
            "SELECT requests, tokens, usd, cooldown_until FROM provider_usage WHERE provider=? AND day=?",
            (provider, self._day()),
        ).fetchone()
        return row

    def available(self, provider: str) -> bool:
        now = time.time()
        limit = self.limit(provider)
        with self._connect() as conn:
            row = self._row(conn, provider)
        if not row:
            return True
        requests, tokens, usd, cooldown_until = row
        if cooldown_until > now:
            return False
        return not (
            (limit.requests and requests >= limit.requests)
            or (limit.tokens and tokens >= limit.tokens)
            or (limit.usd and usd >= limit.usd)
        )

    def record(self, provider: str, tokens: int = 0, usd: float = 0.0) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO provider_usage(provider, day, requests, tokens, usd)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(provider, day) DO UPDATE SET
                     requests=requests+1, tokens=tokens+excluded.tokens, usd=usd+excluded.usd""",
                (provider, self._day(), max(0, int(tokens)), max(0.0, float(usd))),
            )

    def cooldown(self, provider: str, seconds: int, error: str) -> None:
        until = time.time() + max(1, min(int(seconds), 3600))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO provider_usage(provider, day, cooldown_until, last_error)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(provider, day) DO UPDATE SET
                     cooldown_until=excluded.cooldown_until, last_error=excluded.last_error""",
                (provider, self._day(), until, error[:500]),
            )

    def snapshot(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT provider, day, requests, tokens, usd, cooldown_until, last_error FROM provider_usage ORDER BY day DESC, provider"
            ).fetchall()
        return [
            {
                "provider": row[0], "day": row[1], "requests": row[2], "tokens": row[3],
                "usd": row[4], "cooldown_until": row[5], "last_error": row[6],
            }
            for row in rows
        ]
