"""Registro longitudinal e auditável do aprendizado da Atena.

Este módulo mede progresso; não afirma que o modelo ganhou inteligência. Scores só
são comparáveis quando pertencem à mesma versão de benchmark e os snapshots
preservam modelo, tarefas, lições consultadas e regressões.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LearningProgress:
    def __init__(self, db_path: str | Path = "atena_evolution/memory.sqlite3") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_progress (
                    progress_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    model TEXT,
                    benchmark_version TEXT,
                    benchmark_score REAL,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    validated_lesson_count INTEGER NOT NULL DEFAULT 0,
                    lessons_consulted_count INTEGER NOT NULL DEFAULT 0,
                    success_rate REAL,
                    regression_status TEXT NOT NULL DEFAULT 'not_run',
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_progress_created
                    ON learning_progress(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_progress_benchmark
                    ON learning_progress(benchmark_version, created_at DESC);
                CREATE TABLE IF NOT EXISTS lesson_usage (
                    usage_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    lesson_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    consulted_at TEXT NOT NULL,
                    applied INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_lesson_usage_cycle ON lesson_usage(cycle_id);
                """
            )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "LearningProgress":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record_lesson_usage(self, cycle_id: str, query: str, lessons: list[dict[str, Any]]) -> int:
        now = utc_now()
        rows: list[tuple[Any, ...]] = []
        for rank, item in enumerate(lessons, start=1):
            lesson = item.get("lesson", item) if isinstance(item, dict) else {}
            lesson_id = str(lesson.get("lesson_id", "")).strip()
            if not lesson_id:
                continue
            rows.append((f"usage-{uuid.uuid4().hex[:20]}", cycle_id, lesson_id, query[:1000], rank, now, 0))
        with self.connection:
            self.connection.executemany(
                """INSERT INTO lesson_usage
                   (usage_id, cycle_id, lesson_id, query, rank, consulted_at, applied)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    def record_cycle(self, *, cycle_id: str, model: str | None = None,
                     benchmark_version: str | None = None, benchmark_score: float | None = None,
                     evidence_count: int = 0, validated_lesson_count: int = 0,
                     lessons_consulted_count: int = 0, success_rate: float | None = None,
                     regression_status: str = "not_run", payload: dict[str, Any] | None = None) -> str:
        if benchmark_score is not None and not 0 <= float(benchmark_score) <= 1:
            raise ValueError("benchmark_score deve estar entre 0 e 1")
        if success_rate is not None and not 0 <= float(success_rate) <= 1:
            raise ValueError("success_rate deve estar entre 0 e 1")
        if regression_status not in {"not_run", "pass", "fail", "blocked"}:
            raise ValueError("regression_status inválido")
        progress_id = f"progress-{uuid.uuid4().hex[:20]}"
        now = utc_now()
        record = dict(payload or {})
        record.update({
            "progress_id": progress_id,
            "cycle_id": cycle_id,
            "created_at": now,
            "model": model,
            "benchmark_version": benchmark_version,
            "benchmark_score": benchmark_score,
            "evidence_count": int(evidence_count),
            "validated_lesson_count": int(validated_lesson_count),
            "lessons_consulted_count": int(lessons_consulted_count),
            "success_rate": success_rate,
            "regression_status": regression_status,
        })
        with self.connection:
            self.connection.execute(
                """INSERT INTO learning_progress
                   (progress_id, cycle_id, created_at, model, benchmark_version,
                    benchmark_score, evidence_count, validated_lesson_count,
                    lessons_consulted_count, success_rate, regression_status, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (progress_id, cycle_id, now, model, benchmark_version, benchmark_score,
                 int(evidence_count), int(validated_lesson_count), int(lessons_consulted_count),
                 success_rate, regression_status, json.dumps(record, ensure_ascii=False, sort_keys=True)),
            )
        return progress_id

    def recent(self, limit: int = 20, benchmark_version: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if benchmark_version:
            rows = self.connection.execute(
                "SELECT payload_json FROM learning_progress WHERE benchmark_version=? ORDER BY created_at DESC LIMIT ?",
                (benchmark_version, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM learning_progress ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def benchmark_summary(self, benchmark_version: str, limit: int = 30) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        rows = self.connection.execute(
            "SELECT payload_json FROM learning_progress WHERE benchmark_version=? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (benchmark_version, limit),
        ).fetchall()

        scored = [json.loads(row[0]) for row in rows if json.loads(row[0]).get("benchmark_score") is not None]
        if not scored:
            return {
                "decision": "insufficient_data",
                "samples": 0,
                "benchmark_version": benchmark_version,
                "first_score": None,
                "last_score": None,
                "best_score": None,
                "delta": None,
                "regression_failures": 0,
                "scores": [],
            }

        first = float(scored[0]["benchmark_score"])
        last = float(scored[-1]["benchmark_score"])
        best = max(float(item["benchmark_score"]) for item in scored)
        failures = sum(item.get("regression_status") == "fail" for item in scored)
        delta = round(last - first, 6)

        if failures > 0 and delta > 0:
            decision = "mixed"
        elif failures > 0:
            decision = "regressed"
        elif delta > 0:
            decision = "improved"
        elif abs(delta) < 1e-9:
            decision = "stable"
        else:
            decision = "regressed"

        return {
            "decision": decision,
            "samples": len(scored),
            "benchmark_version": benchmark_version,
            "first_score": first,
            "last_score": last,
            "best_score": best,
            "delta": delta,
            "regression_failures": failures,
            "scores": [float(item["benchmark_score"]) for item in scored],
        }

    def trend(self, benchmark_version: str, limit: int = 30) -> dict[str, Any]:
        return self.benchmark_summary(benchmark_version, limit=limit)

    def counts(self) -> dict[str, int]:
        progress = int(self.connection.execute("SELECT COUNT(*) FROM learning_progress").fetchone()[0])
        usage = int(self.connection.execute("SELECT COUNT(*) FROM lesson_usage").fetchone()[0])
        return {"progress_snapshots": progress, "lesson_usage_records": usage}
