"""Redis Streams queue for asynchronous ATENA RAG audit/access events."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

STREAM = "atena:rag-events"
GROUP = "atena-audit-workers"


def make_query_event(
    *,
    tenant_id: str,
    question: str,
    memory_ids: list[int],
    user_id: str | None,
    results_count: int,
    event_id: str | None = None,
) -> dict[str, str]:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": "rag.query",
        "tenant_id": tenant_id,
        "question_hash": hashlib.sha256(question[:200].encode("utf-8")).hexdigest(),
        "memory_ids": json.dumps(memory_ids),
        "user_id": user_id or "system",
        "results_count": str(results_count),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def publish_event(redis_client: Any, event: dict[str, str], stream: str = STREAM) -> str:
    """Publish one event; Redis Streams provides at-least-once delivery."""
    return str(redis_client.xadd(stream, event, maxlen=100_000, approximate=True))


def ensure_consumer_group(redis_client: Any, stream: str = STREAM, group: str = GROUP) -> None:
    try:
        redis_client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def process_batch(conn: Any, events: Iterable[tuple[str, dict[str, str]]]) -> dict[str, int]:
    """Apply a batch in one SQLite transaction.

    The unique ``audit_log.event_id`` index makes retries safe. Access counters
    are incremented only when the audit event is inserted for the first time.
    """
    inserted = 0
    duplicates = 0
    access_updates = Counter()
    rows = list(events)
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for stream_id, event in rows:
            if event.get("event_type") != "rag.query":
                continue
            event_id = event.get("event_id") or stream_id
            details = json.dumps(
                {
                    "event_id": event_id,
                    "question_hash": event.get("question_hash"),
                    "results_count": event.get("results_count", "0"),
                    "stream_id": stream_id,
                },
                ensure_ascii=False,
            )
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO audit_log
                    (tenant_id, action, user_id, timestamp, details_json, event_id)
                VALUES (?, 'rag.query', ?, ?, ?, ?)
                """,
                (
                    event.get("tenant_id", "unknown"),
                    event.get("user_id", "system"),
                    event.get("created_at") or now,
                    details,
                    event_id,
                ),
            )
            if cursor.rowcount == 0:
                duplicates += 1
                continue
            inserted += 1
            for memory_id in json.loads(event.get("memory_ids", "[]")):
                access_updates[int(memory_id)] += 1

        for memory_id, amount in access_updates.items():
            conn.execute(
                """
                UPDATE memory
                SET access_count = access_count + ?, last_accessed = ?
                WHERE id = ?
                """,
                (amount, now, memory_id),
            )
    return {
        "events_received": len(rows),
        "events_inserted": inserted,
        "duplicates_ignored": duplicates,
        "access_updates": sum(access_updates.values()),
    }


def run_worker(
    *,
    redis_client: Any,
    db_path: str,
    stream: str = STREAM,
    group: str = GROUP,
    consumer: str | None = None,
    batch_size: int = 100,
    block_ms: int = 1000,
) -> None:
    """Run a single SQLite writer consuming Redis Streams batches."""
    import sqlite3

    consumer = consumer or f"worker-{os.getpid()}"
    ensure_consumer_group(redis_client, stream, group)
    # O worker pode iniciar antes do processo RAG criar o banco. Reutilizar a
    # inicialização oficial também aplica a migração event_id e os índices.
    from core.enterprise_memory_rag import TenantMemoryRAG

    TenantMemoryRAG(db_path, enable_embeddings=False)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        while True:
            response = redis_client.xreadgroup(
                group, consumer, {stream: ">"}, count=batch_size, block=block_ms
            )
            if not response:
                continue
            for _, messages in response:
                events = [(str(stream_id), {str(k): str(v) for k, v in fields.items()})
                          for stream_id, fields in messages]
                process_batch(conn, events)
                redis_client.xack(stream, group, *(stream_id for stream_id, _ in events))
    finally:
        conn.close()
