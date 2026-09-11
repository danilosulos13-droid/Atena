"""Base de conhecimento persistente para pesquisa multiassunto da Atena.

Mantém documentos, trechos, metadados, proveniência e um índice FTS5 no mesmo
SQLite da memória. A base é append-friendly, deduplicada por hash e separa
fonte bruta de conclusões geradas pelo modelo.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    topic TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kdocs_topic ON knowledge_documents(topic);
CREATE INDEX IF NOT EXISTS idx_kdocs_domain ON knowledge_documents(domain);
CREATE INDEX IF NOT EXISTS idx_kdocs_fetched ON knowledge_documents(fetched_at DESC);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    UNIQUE(document_id, chunk_index),
    UNIQUE(document_id, text_hash)
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    title,
    topic,
    text,
    domain
);
CREATE TABLE IF NOT EXISTS knowledge_research (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    topic TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    document_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    summary TEXT
);
"""


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


def _canonical(url: str) -> str:
    return re.sub(r"#.*$", "", url.strip()).rstrip("/")


def _chunks(text: str, size: int = 1800, overlap: int = 250) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [text[i:i + size] for i in range(0, len(text), step)]


class KnowledgeBase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "KnowledgeBase":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def add_document(self, *, url: str, title: str, topic: str, content: str, metadata: dict[str, Any] | None = None) -> tuple[str, int, bool]:
        content = re.sub(r"\s+", " ", content).strip()
        if not content:
            return "", 0, False
        canonical = _canonical(url)
        content_hash = _hash(content)
        existing = self.db.execute("SELECT id FROM knowledge_documents WHERE content_hash=?", (content_hash,)).fetchone()
        if existing:
            return str(existing[0]), 0, False
        doc_id = _id("doc", canonical + "|" + content_hash)
        from urllib.parse import urlparse
        domain = urlparse(canonical).netloc.lower()
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute(
                "INSERT INTO knowledge_documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                (doc_id, canonical, canonical, title[:500] or canonical, domain, topic[:300], now, content_hash, content, __import__('json').dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
            )
            count = 0
            for index, chunk in enumerate(_chunks(content)):
                chunk_id = _id("chunk", doc_id + f"|{index}|" + _hash(chunk))
                text_hash = _hash(chunk)
                self.db.execute("INSERT INTO knowledge_chunks VALUES (?,?,?,?,?)", (chunk_id, doc_id, index, chunk, text_hash))
                self.db.execute("INSERT INTO knowledge_fts VALUES (?,?,?,?,?,?)", (chunk_id, doc_id, title[:500], topic[:300], chunk, domain))
                count += 1
        return doc_id, count, True

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        terms = " ".join(re.findall(r"[\wÀ-ÿ]{3,}", query.lower()))
        if not terms:
            return []
        try:
            rows = self.db.execute(
                "SELECT f.chunk_id, f.document_id, f.title, f.topic, f.domain, f.text, d.url, d.fetched_at "
                "FROM knowledge_fts f JOIN knowledge_documents d ON d.id=f.document_id "
                "WHERE knowledge_fts MATCH ? ORDER BY bm25(knowledge_fts) LIMIT ?", (terms, max(1, min(limit, 100)))
            ).fetchall()
        except sqlite3.OperationalError:
            rows = self.db.execute(
                "SELECT f.chunk_id, f.document_id, f.title, f.topic, f.domain, f.text, d.url, d.fetched_at "
                "FROM knowledge_fts f JOIN knowledge_documents d ON d.id=f.document_id "
                "WHERE f.text LIKE ? ORDER BY d.fetched_at DESC LIMIT ?", (f"%{terms.split()[0]}%", max(1, min(limit, 100)))
            ).fetchall()
        keys = ("chunk_id", "document_id", "title", "topic", "domain", "text", "url", "fetched_at")
        return [dict(zip(keys, row)) for row in rows]

    def stats(self) -> dict[str, int]:
        return {
            "documents": int(self.db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0]),
            "chunks": int(self.db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]),
            "topics": int(self.db.execute("SELECT COUNT(DISTINCT topic) FROM knowledge_documents").fetchone()[0]),
            "domains": int(self.db.execute("SELECT COUNT(DISTINCT domain) FROM knowledge_documents").fetchone()[0]),
        }

    def record_research(self, *, query: str, topic: str, started_at: str, source_count: int, document_count: int, chunk_count: int, status: str, summary: str = "") -> str:
        rid = _id("research", query + "|" + started_at)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO knowledge_research VALUES (?,?,?,?,?,?,?,?,?,?)", (rid, query, topic, started_at, datetime.now(timezone.utc).isoformat(), source_count, document_count, chunk_count, status, summary[:5000]))
        return rid
