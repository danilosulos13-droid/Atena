from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from core.atena_audit_queue import process_batch
from core.enterprise_memory_rag import BM25, TenantMemoryRAG, build_reasoning_trace


def test_memory_upsert_query_and_retention(tmp_path):
    store = TenantMemoryRAG(tmp_path / "memory.db")
    up = store.upsert(
        tenant_id="t1",
        content="Use cache distribuído para reduzir latência p95",
        citation="runbook://cache",
        classification="internal",
        tags=["cache"],
    )
    assert up["status"] == "ok"

    result = store.query("t1", "como reduzir latência p95", top_k=2)
    assert result["status"] == "ok"
    assert result["citations_required"] is True
    assert len(result["results"]) >= 1

    purged = store.purge_expired({"public": 0, "internal": 0, "confidential": 0, "default": 0})
    assert purged["status"] == "ok"


def test_reasoning_trace_redacts_secret():
    trace = build_reasoning_trace(
        steps=["usar token ghp_ABCDEF1234567890XYZ1234"],
        citations=["doc://security"],
    )
    assert trace["status"] == "ok"
    assert "[REDACTED_SECRET]" in trace["steps"][0]


def test_reasoning_trace_redacts_shorter_github_token_like_string():
    trace = build_reasoning_trace(
        steps=["registrar credencial ghp_ABCDEF1234567890XYZ para auditoria"],
        citations=["doc://security"],
    )
    assert trace["status"] == "ok"
    assert "[REDACTED_SECRET]" in trace["steps"][0]


def test_concurrent_queries_retry_sqlite_writes(tmp_path):
    store = TenantMemoryRAG(tmp_path / "concurrent.db", enable_embeddings=False)
    store.upsert(
        tenant_id="t1",
        content="Runbook de recuperação do serviço e controle de concorrência",
        citation="runbook://concurrency",
        classification="internal",
        tags=["operations"],
    )

    def query(index):
        result = store.query(
            "t1",
            "como recuperar o serviço",
            top_k=1,
            use_cache=False,
            user_id=f"test-{index}",
        )
        return result["status"], result["results"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(query, range(64)))

    assert all(status == "ok" and rows for status, rows in results)


def test_audit_event_id_is_unique_and_batch_is_idempotent(tmp_path):
    db = tmp_path / "batch.db"
    store = TenantMemoryRAG(db, enable_embeddings=False)
    up = store.upsert(
        tenant_id="t1",
        content="Documento de operações para teste de auditoria",
        citation="doc://batch",
        tags=["operations"],
    )
    memory_id = up["memory_id"]
    event = {
        "event_id": "evt-1",
        "event_type": "rag.query",
        "tenant_id": "t1",
        "user_id": "tester",
        "memory_ids": json.dumps([memory_id, memory_id]),
        "question_hash": "hash",
        "results_count": "1",
    }
    conn = sqlite3.connect(db)
    first = process_batch(conn, [("stream-1", event)])
    second = process_batch(conn, [("stream-2", event)])
    assert first["events_inserted"] == 1
    assert second["duplicates_ignored"] == 1
    assert conn.execute("select count(*) from audit_log where event_id='evt-1'").fetchone()[0] == 1
    assert conn.execute("select access_count from memory where id=?", (memory_id,)).fetchone()[0] == 2
    conn.close()


def test_bm25_precomputes_doc_freq_and_scores_only_posting_candidates():
    index = BM25()
    index.index([
        "alpha alpha sistema",
        "beta sistema",
        "documento sem o termo",
    ])

    assert index.doc_freq("alpha") == 1
    assert index.doc_freq("sistema") == 2
    assert index.doc_freq("ausente") == 0
    assert index.postings["alpha"] == [(0, 2)]
    assert index.search("alpha", top_k=5)[0][0] == 0
    assert len(index.search("alpha", top_k=5)) == 1


def test_fts5_feature_flag_queries_persistent_index(tmp_path, monkeypatch):
    monkeypatch.setenv("ATENA_LEXICAL_ENGINE", "fts5")
    store = TenantMemoryRAG(tmp_path / "fts.db", enable_embeddings=False)
    store.upsert(
        tenant_id="t1",
        content="Procedimento de recuperação rápida do serviço",
        citation="doc://fts",
        classification="public",
        tags=["operations"],
    )

    result = store.query("t1", "recuperação rápida", top_k=1, min_score=0.01)
    assert result["status"] == "ok"
    assert result["results"][0]["citation"] == "doc://fts"
