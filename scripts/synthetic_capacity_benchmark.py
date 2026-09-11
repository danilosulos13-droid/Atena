#!/usr/bin/env python3
"""Structural capacity benchmark for ATENA's SQLite + BM25 layout.

This intentionally uses deterministic synthetic chunks. It measures infrastructure
limits only; it does not measure retrieval quality on a real corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import sqlite3
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "results" / "synthetic-capacity"

SCHEMA = """
CREATE TABLE memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    content TEXT NOT NULL,
    citation TEXT NOT NULL,
    classification TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    source TEXT,
    embedding BLOB,
    metadata_json TEXT,
    content_hash TEXT
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    action TEXT NOT NULL,
    memory_id INTEGER,
    user_id TEXT,
    timestamp TEXT NOT NULL,
    details_json TEXT,
    event_id TEXT
);
CREATE INDEX idx_memory_tenant_class ON memory(tenant_id, classification);
CREATE INDEX idx_memory_content_hash ON memory(content_hash);
CREATE INDEX idx_audit_event_id ON audit_log(event_id);
"""

TOPICS = (
    "inteligencia artificial", "ciberseguranca", "dados", "cloud native",
    "governanca", "observabilidade", "privacidade", "engenharia de software",
)


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def chunk_row(i: int) -> tuple:
    topic = TOPICS[i % len(TOPICS)]
    tenant = "atena-synthetic"
    content = (
        f"Documento {i} da Atena sobre {topic}. "
        f"Este chunk descreve controles operacionais, evidencias, riscos, "
        f"indicadores e procedimentos de validacao para o dominio {topic}. "
        f"Referencia deterministica {i:08d} e lote {i // 1000:06d}."
    )
    digest = hashlib.md5(content.encode()).hexdigest()
    now = "2026-09-10T00:00:00+00:00"
    tags = json.dumps([topic, "synthetic", f"batch-{i // 10000}"])
    return (
        tenant, content, f"synthetic://atena/{i:08d}", "public", tags,
        now, now, 0, None, "synthetic-capacity", None, "{}", digest,
    )


def create_db(path: Path, total: int, batch_size: int) -> dict:
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(SCHEMA)
    sql = """INSERT INTO memory
        (tenant_id, content, citation, classification, tags_json,
         created_at, updated_at, access_count, last_accessed, source,
         embedding, metadata_json, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        conn.executemany(sql, (chunk_row(i) for i in range(start, end)))
        conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    return {"ingest_seconds": round(time.perf_counter() - t0, 3), "rss_mb": round(rss_mb(), 1)}


def run_sqlite_probe(path: Path) -> dict:
    conn = sqlite3.connect(path)
    t0 = time.perf_counter()
    count = conn.execute("SELECT count(*) FROM memory WHERE tenant_id=?", ("atena-synthetic",)).fetchone()[0]
    count_ms = (time.perf_counter() - t0) * 1000
    latencies = []
    for topic in TOPICS[:5]:
        t1 = time.perf_counter()
        rows = conn.execute(
            "SELECT id, content, citation FROM memory WHERE tenant_id=? AND content LIKE ? LIMIT 5",
            ("atena-synthetic", f"%{topic}%"),
        ).fetchall()
        latencies.append((time.perf_counter() - t1) * 1000)
        assert rows
    conn.close()
    return {
        "row_count": count,
        "count_ms": round(count_ms, 3),
        "sql_probe_p50_ms": round(statistics.median(latencies), 3),
        "sql_probe_p95_ms": round(max(latencies), 3),
    }


def run_rag_probe(path: Path) -> dict:
    import sys
    sys.path.insert(0, str(ROOT))
    from core.enterprise_memory_rag import TenantMemoryRAG
    t0 = time.perf_counter()
    rag = TenantMemoryRAG(path, enable_embeddings=False)
    init_seconds = time.perf_counter() - t0
    latencies = []
    statuses = []
    for question in (
        "evidencias de inteligencia artificial",
        "controles de ciberseguranca",
    ):
        t1 = time.perf_counter()
        result = rag.query("atena-synthetic", question, top_k=5, min_score=0.01, use_cache=False)
        latencies.append((time.perf_counter() - t1) * 1000)
        statuses.append(result.get("status"))
    return {
        "rag_bm25_init_seconds": round(init_seconds, 3),
        "rag_query_statuses": statuses,
        "rag_query_p50_ms": round(statistics.median(latencies), 3),
        "rag_query_p95_ms": round(max(latencies), 3),
        "rss_mb_after_rag": round(rss_mb(), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--levels", default="100000,500000,1000000")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--skip-rag", action="store_true")
    args = parser.parse_args()
    levels = [int(value) for value in args.levels.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    all_results = []
    for total in levels:
        path = args.out / f"atena_synthetic_{total}.sqlite3"
        print(f"GENERATE chunks={total}", flush=True)
        result = {"chunks": total, "db_path": str(path)}
        result.update(create_db(path, total, args.batch_size))
        result["db_size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)
        result.update(run_sqlite_probe(path))
        if not args.skip_rag:
            print(f"RAG_INIT chunks={total}", flush=True)
            result.update(run_rag_probe(path))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        all_results.append(result)
    output = args.out / "synthetic_capacity_results.json"
    output.write_text(json.dumps({"levels": all_results}, ensure_ascii=False, indent=2) + "\n")
    print(f"RESULTS {output}", flush=True)


if __name__ == "__main__":
    main()
