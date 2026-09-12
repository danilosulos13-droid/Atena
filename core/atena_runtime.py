"""Runtime persistente da Atena.

Oferece uma fila SQLite durável, ciclo de worker, registro de conectores sem
armazenar segredos e um roteador de ferramentas com perfil de navegador
persistente. A camada é deliberadamente agnóstica ao provedor de IA: tarefas
podem ser executadas por um handler local ou encaminhadas a um worker externo.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.general_tool_router import GeneralToolRouter


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    created_at: float
    updated_at: float
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0

    def public(self) -> dict[str, Any]:
        return asdict(self)


class PersistentRuntime:
    """Fila e estado persistentes para um único processo de Atena."""

    def __init__(self, db_path: str | Path | None = None, *, browser_profile: str | Path | None = None) -> None:
        self.db_path = Path(db_path or os.getenv("ATENA_RUNTIME_DB", "atena_evolution/runtime.sqlite3"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._wake = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._stop = False
        self._tool_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="atena-tools")
        self.handlers: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]] = {}
        self.router = GeneralToolRouter(
            audit_path=Path(os.getenv("ATENA_TOOL_ROUTER_AUDIT", "atena_evolution/tool_router_audit.jsonl")),
        )
        if browser_profile:
            self.router.browser.user_data_dir = Path(browser_profile).resolve()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_tasks (
                    task_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_runtime_tasks_status ON runtime_tasks(status, created_at);
                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_connectors (
                    name TEXT PRIMARY KEY,
                    connector_type TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def _emit(self, task_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_events(task_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                (task_id, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def register_handler(self, kind: str, handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]) -> None:
        if not kind or not callable(handler):
            raise ValueError("handler inválido")
        self.handlers[kind] = handler

    async def dispatch_tool(self, name: str, arguments: dict[str, Any] | None = None, *, approval: bool = False):
        """Executa o roteador síncrono fora do event loop.

        Playwright Sync API e outras ferramentas bloqueantes não devem ser
        chamadas diretamente dentro do worker assíncrono.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._tool_executor,
            lambda: self.router.dispatch(name, arguments, approval=approval),
        )

    def register_connector(self, name: str, connector_type: str, config: dict[str, Any] | None = None, *, enabled: bool = True) -> dict[str, Any]:
        """Registra metadados; valores de segredo devem ser referências de ambiente."""
        if not name or not connector_type:
            raise ValueError("name e connector_type são obrigatórios")
        safe = dict(config or {})
        for key in list(safe):
            if any(marker in key.casefold() for marker in ("token", "secret", "password", "api_key", "private_key")):
                safe[key] = "[REDACTED: use ENV reference]"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO runtime_connectors(name,connector_type,config_json,enabled,created_at,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET connector_type=excluded.connector_type,
                   config_json=excluded.config_json, enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (name, connector_type, json.dumps(safe, ensure_ascii=False), int(enabled), now, now),
            )
        return {"name": name, "connector_type": connector_type, "enabled": enabled, "config": safe}

    def list_connectors(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name,connector_type,config_json,enabled,created_at,updated_at FROM runtime_connectors ORDER BY name").fetchall()
        return [
            {"name": row[0], "connector_type": row[1], "config": json.loads(row[2]), "enabled": bool(row[3]), "created_at": row[4], "updated_at": row[5]}
            for row in rows
        ]

    def enqueue(self, kind: str, payload: dict[str, Any], *, task_id: str | None = None) -> TaskRecord:
        now = time.time()
        record = TaskRecord(task_id or f"task-{uuid.uuid4().hex}", kind, payload, "queued", now, now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_tasks(task_id,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (record.task_id, record.kind, json.dumps(record.payload, ensure_ascii=False), record.status, now, now),
            )
        self._emit(record.task_id, "task.queued", {"kind": kind})
        if self._worker_task and not self._worker_task.done():
            self._wake.set()
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runtime_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return TaskRecord(row[0], row[1], json.loads(row[2]), row[3], row[4], row[5], json.loads(row[6]) if row[6] else None, row[7], row[8])

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runtime_tasks ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [TaskRecord(row[0], row[1], json.loads(row[2]), row[3], row[4], row[5], json.loads(row[6]) if row[6] else None, row[7], row[8]) for row in rows]

    def _claim_next(self) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runtime_tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            now = time.time()
            conn.execute("UPDATE runtime_tasks SET status='running',updated_at=?,attempts=attempts+1 WHERE task_id=? AND status='queued'", (now, row[0]))
        record = self.get_task(row[0])
        if record:
            self._emit(record.task_id, "task.started", {"kind": record.kind, "attempts": record.attempts})
        return record

    async def _run_one(self, record: TaskRecord) -> None:
        handler = self.handlers.get(record.kind)
        try:
            if handler is None:
                raise RuntimeError(f"no_handler:{record.kind}")
            output = handler(record.payload)
            if asyncio.iscoroutine(output):
                output = await output
            result = dict(output or {})
            now = time.time()
            with self._connect() as conn:
                conn.execute("UPDATE runtime_tasks SET status='succeeded',updated_at=?,result_json=?,error=NULL WHERE task_id=?", (now, json.dumps(result, ensure_ascii=False), record.task_id))
            self._emit(record.task_id, "task.succeeded", result)
        except Exception as exc:
            now = time.time()
            with self._connect() as conn:
                conn.execute("UPDATE runtime_tasks SET status='failed',updated_at=?,error=? WHERE task_id=?", (now, f"{type(exc).__name__}: {exc}", record.task_id))
            self._emit(record.task_id, "task.failed", {"error": f"{type(exc).__name__}: {exc}"})

    async def _worker(self) -> None:
        while not self._stop:
            record = self._claim_next()
            if record:
                await self._run_one(record)
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stop = False
            self._worker_task = asyncio.create_task(self._worker(), name="atena-runtime-worker")

    async def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._worker_task:
            await self._worker_task
        self._worker_task = None
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._tool_executor, self.router.close)
        self._tool_executor.shutdown(wait=True)

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            queued = conn.execute("SELECT COUNT(*) FROM runtime_tasks WHERE status='queued'").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM runtime_tasks WHERE status='running'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM runtime_tasks WHERE status='failed'").fetchone()[0]
        return {"status": "healthy", "worker_running": bool(self._worker_task and not self._worker_task.done()), "queued": queued, "running": running, "failed": failed, "connectors": len(self.list_connectors()), "database": str(self.db_path)}


__all__ = ["PersistentRuntime", "TaskRecord"]
