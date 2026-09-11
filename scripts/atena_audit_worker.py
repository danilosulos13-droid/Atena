#!/usr/bin/env python3
from __future__ import annotations

import os

import redis

from core.atena_audit_queue import run_worker


if __name__ == "__main__":
    client = redis.Redis.from_url(
        os.getenv("ATENA_REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    run_worker(
        redis_client=client,
        db_path=os.getenv(
            "ATENA_RAG_DB",
            "atena_evolution/rag/atena_jarvis.sqlite3",
        ),
        stream=os.getenv("ATENA_REDIS_STREAM", "atena:rag-events"),
        group=os.getenv("ATENA_REDIS_GROUP", "atena-audit-workers"),
        consumer=os.getenv("ATENA_REDIS_CONSUMER"),
        batch_size=int(os.getenv("ATENA_AUDIT_BATCH_SIZE", "100")),
        block_ms=int(os.getenv("ATENA_AUDIT_BLOCK_MS", "1000")),
    )
