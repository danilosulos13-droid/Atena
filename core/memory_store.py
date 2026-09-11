"""Armazenamento transacional de memória episódica e ponte opcional para FAISS."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.episodic_memory import (
    EpisodicMemoryError,
    build_episode,
    compute_content_hash,
    validate_record,
    verify_hash_chain,
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    sequence INTEGER UNIQUE,
    record_type TEXT NOT NULL,
    task_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    benchmark_version TEXT,
    created_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    previous_record_hash TEXT,
    status TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    lifecycle_state TEXT NOT NULL,
    supersedes_id TEXT REFERENCES episodes(id),
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provenance (
    episode_id TEXT PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT,
    model TEXT,
    model_digest TEXT,
    system_version TEXT NOT NULL,
    workflow_run_id TEXT,
    input_digest TEXT,
    verification_method TEXT,
    raw_content_redacted INTEGER NOT NULL DEFAULT 0 CHECK (raw_content_redacted IN (0, 1))
);
CREATE TABLE IF NOT EXISTS evidence_links (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    evidence_episode_id TEXT NOT NULL REFERENCES episodes(id),
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight >= 0 AND weight <= 1),
    PRIMARY KEY (episode_id, evidence_episode_id, relation)
);
CREATE TABLE IF NOT EXISTS research_intents (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    command TEXT NOT NULL,
    topic TEXT NOT NULL,
    question TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    cycle_id TEXT,
    result_json TEXT,
    UNIQUE(chat_id, topic, status)
);
CREATE INDEX IF NOT EXISTS idx_research_intents_queue ON research_intents(status, created_at);
CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    category TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    average_latency_ms REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_episodes_task ON episodes(task_id);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provenance_source ON provenance(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_target ON evidence_links(evidence_episode_id);
"""


class MemoryStore:
    """Repositório SQLite append-only para episódios e proveniência."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(episodes)").fetchall()}
        if "sequence" not in columns:
            self.connection.execute("ALTER TABLE episodes ADD COLUMN sequence INTEGER")
            rows = self.connection.execute("SELECT id FROM episodes ORDER BY created_at ASC, id ASC").fetchall()
            for index, row in enumerate(rows, start=1):
                self.connection.execute("UPDATE episodes SET sequence=? WHERE id=?", (index, row[0]))
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_sequence ON episodes(sequence)")
        self.connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _last_hash(self) -> str | None:
        row = self.connection.execute(
            "SELECT content_hash FROM episodes ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else None

    def append(self, record: dict[str, Any], *, link_previous: bool = True) -> str:
        """Insere um episódio; repetir o mesmo episódio é idempotente."""
        value = validate_record(record, verify_hash=True)
        provenance = value["provenance"]
        if link_previous and provenance.get("previous_record_hash") is None:
            provenance["previous_record_hash"] = self._last_hash()
            value["content_hash"] = compute_content_hash(value)
            provenance["content_hash"] = value["content_hash"]
            value = validate_record(value, verify_hash=True)

        existing = self.connection.execute(
            "SELECT content_hash, record_json FROM episodes WHERE id = ?", (value["memory_id"],)
        ).fetchone()
        if existing:
            if existing[0] == value["content_hash"]:
                return value["memory_id"]
            # O primeiro append pode ter preenchido previous_record_hash e
            # recalculado o hash. Para idempotência, compare a carga lógica,
            # ignorando apenas os campos derivados da cadeia.
            stored = json.loads(existing[1])
            candidate = json.loads(json.dumps(value, ensure_ascii=False))
            for item in (stored, candidate):
                item.pop("content_hash", None)
                item.get("provenance", {}).pop("content_hash", None)
                item.get("provenance", {}).pop("previous_record_hash", None)
            if stored == candidate:
                return value["memory_id"]
            raise EpisodicMemoryError(f"memory_id já existe com conteúdo diferente: {value['memory_id']}")

        event_json = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        subject = value["subject"]
        evidence = value["evidence"]
        lifecycle = value["lifecycle"]
        next_sequence = self.connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM episodes").fetchone()[0]
        with self.connection:
            self.connection.execute(
                """INSERT INTO episodes
                (id, sequence, record_type, task_id, domain, benchmark_version, created_at,
                 record_json, content_hash, previous_record_hash, status, confidence,
                 lifecycle_state, supersedes_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    value["memory_id"], next_sequence, value["record_type"], subject["task_id"],
                    subject["domain"], subject.get("benchmark_version"), value["created_at"],
                    event_json, value["content_hash"], provenance.get("previous_record_hash"),
                    evidence["status"], float(evidence["confidence"]), lifecycle["state"],
                    lifecycle.get("supersedes"), provenance["source_type"],
                ),
            )
            self.connection.execute(
                """INSERT INTO provenance
                (episode_id, source_type, source_id, source_url, model, model_digest,
                 system_version, workflow_run_id, input_digest, verification_method,
                 raw_content_redacted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    value["memory_id"], provenance["source_type"], provenance["source_id"],
                    provenance.get("source_url"), provenance.get("model"),
                    provenance.get("model_digest"), provenance["system_version"],
                    provenance.get("workflow_run_id"), value["event"].get("input_digest"),
                    evidence.get("verification_method"),
                    int(value.get("privacy", {}).get("contains_secret", False)),
                ),
            )
        return value["memory_id"]

    def add_simple(
        self,
        *,
        output: str,
        task_id: str,
        domain: str,
        source_type: str,
        source_id: str,
        system_version: str,
        model: str | None = None,
        record_type: str = "observation",
        confidence: float = 0.0,
        status: str = "unverified",
    ) -> str:
        record = build_episode(
            record_type=record_type,
            task_id=task_id,
            domain=domain,
            output=output,
            source_type=source_type,
            source_id=source_id,
            system_version=system_version,
            model=model,
            confidence=confidence,
            status=status,
        )
        return self.append(record)

    def get(self, memory_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT record_json FROM episodes WHERE id = ?", (memory_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def recent(self, limit: int = 20, *, task_id: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if task_id:
            rows = self.connection.execute(
                "SELECT record_json FROM episodes WHERE task_id = ? ORDER BY sequence DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT record_json FROM episodes ORDER BY sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def iter_ordered(self) -> Iterable[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT record_json FROM episodes ORDER BY sequence ASC"
        )
        for row in rows:
            yield json.loads(row[0])

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])

    def verify_integrity(self) -> str | None:
        records = list(self.iter_ordered())
        last_hash = verify_hash_chain(records)
        for record in records:
            row = self.connection.execute(
                "SELECT content_hash FROM episodes WHERE id = ?", (record["memory_id"],)
            ).fetchone()
            if not row or row[0] != record["content_hash"]:
                raise EpisodicMemoryError(f"hash divergente no banco: {record['memory_id']}")
        return last_hash

    def enqueue_research(self, chat_id: int | str, topic: str, question: str | None = None) -> str:
        import uuid
        from datetime import datetime, timezone
        topic = " ".join(str(topic).split()).strip()
        if not topic or len(topic) > 240:
            raise ValueError("tema de pesquisa vazio ou longo demais")
        intent_id = f"intent-{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self.connection:
            existing = self.connection.execute(
                "SELECT id FROM research_intents WHERE chat_id=? AND topic=? AND status IN ('pending','processing')",
                (str(chat_id), topic),
            ).fetchone()
            if existing:
                return str(existing[0])
            self.connection.execute(
                """INSERT INTO research_intents(id, chat_id, command, topic, question, status, created_at)
                   VALUES (?, ?, 'research', ?, ?, 'pending', ?)""",
                (intent_id, str(chat_id), topic, question, now),
            )
        return intent_id

    def claim_next_research(self) -> dict[str, Any] | None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM research_intents WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self.connection.execute(
                "UPDATE research_intents SET status='processing', claimed_at=? WHERE id=? AND status='pending'",
                (now, row["id"]),
            )
        return dict(self.connection.execute("SELECT * FROM research_intents WHERE id=?", (row["id"],)).fetchone())

    def complete_research(self, intent_id: str, cycle_id: str, result: dict[str, Any], failed: bool = False) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        status = "failed" if failed else "completed"
        with self.connection:
            self.connection.execute(
                "UPDATE research_intents SET status=?, completed_at=?, cycle_id=?, result_json=? WHERE id=?",
                (status, now, cycle_id, json.dumps(result, ensure_ascii=False, sort_keys=True), intent_id),
            )

    def pending_research(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM research_intents WHERE status IN ('pending','processing') ORDER BY created_at LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def link_evidence(self, episode_id: str, evidence_episode_id: str, relation: str, weight: float = 1.0) -> None:
        allowed = {"supports", "contradicts", "derived_from", "duplicates", "revalidates"}
        if relation not in allowed:
            raise ValueError(f"relação de evidência inválida: {relation}")
        if episode_id == evidence_episode_id:
            raise ValueError("um episódio não pode ser evidência de si mesmo")
        if not 0 <= weight <= 1:
            raise ValueError("weight deve estar entre 0 e 1")
        for identifier in (episode_id, evidence_episode_id):
            if not self.connection.execute("SELECT 1 FROM episodes WHERE id=?", (identifier,)).fetchone():
                raise EpisodicMemoryError(f"episódio inexistente: {identifier}")
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO evidence_links(episode_id, evidence_episode_id, relation, weight) VALUES (?, ?, ?, ?)",
                (episode_id, evidence_episode_id, relation, weight),
            )

    def evidence_for(self, episode_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT e.record_json, p.source_id, p.source_type, l.relation, l.weight
               FROM evidence_links l
               JOIN episodes e ON e.id = l.evidence_episode_id
               LEFT JOIN provenance p ON p.episode_id = e.id
               WHERE l.episode_id = ? ORDER BY l.weight DESC""",
            (episode_id,),
        ).fetchall()
        return [{"record": json.loads(row[0]), "source_id": row[1], "source_type": row[2], "relation": row[3], "weight": row[4]} for row in rows]

    def evidence_summary(self, episode_id: str) -> dict[str, Any]:
        links = self.evidence_for(episode_id)
        supporting = [item for item in links if item["relation"] in {"supports", "revalidates"}]
        contradicting = [item for item in links if item["relation"] == "contradicts"]
        independent_sources = {item["source_id"] for item in supporting if item.get("source_id")}
        return {
            "episode_id": episode_id,
            "total_links": len(links),
            "supporting_links": len(supporting),
            "contradicting_links": len(contradicting),
            "independent_sources": len(independent_sources),
            "supported_weight": round(sum(float(item["weight"]) for item in supporting), 4),
            "contradicted_weight": round(sum(float(item["weight"]) for item in contradicting), 4),
            "status": "contradicted" if contradicting else ("supported" if len(independent_sources) >= 2 else "unverified"),
        }

    def promote_from_evidence(self, episode_id: str, *, min_sources: int = 2, confirm_sources: int = 3) -> str:
        summary = self.evidence_summary(episode_id)
        support = float(summary["supported_weight"])
        contradiction = float(summary["contradicted_weight"])
        confidence = round(max(0.0, min(1.0, support / (support + contradiction))) if support + contradiction > 0 else 0.0, 4)
        if summary["contradicting_links"]:
            status = "contested"
        elif summary["independent_sources"] >= confirm_sources and confidence >= 0.8:
            status = "confirmed"
        elif summary["independent_sources"] >= min_sources and confidence >= 0.6:
            status = "supported"
        else:
            status = "unverified"
        with self.connection:
            self.connection.execute("UPDATE episodes SET status=?, confidence=? WHERE id=?", (status, confidence, episode_id))
        return status

    def export_json(self, path: str | Path, limit: int | None = None) -> int:
        records = list(self.iter_ordered())
        if limit is not None:
            records = records[-max(1, int(limit)):]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return len(records)


class FaissMemoryIndex:
    """Índice FAISS derivado, com IDs persistidos no SQLite como fonte de verdade.

    A classe reutiliza `SentenceTransformerEmbedder` e `FAISSIndex` do motor
    semântico existente. FAISS nunca é usado para provar integridade: se o
    índice for perdido, ele deve ser reconstruído a partir do SQLite.
    """

    def __init__(
        self,
        store: MemoryStore,
        index_path: str | Path,
        metadata_path: str | Path,
        model_name: str = "all-MiniLM-L6-v2",
        use_cache: bool = True,
    ):
        try:
            from core.atena_semantic_memory import CachedEmbedder, FAISSIndex, SentenceTransformerEmbedder
        except Exception as exc:
            raise RuntimeError("dependências do FAISS/SentenceTransformers indisponíveis") from exc
        self.store = store
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        base = SentenceTransformerEmbedder(model_name)
        self.embedder = CachedEmbedder(base) if use_cache else base
        self.faiss_index = FAISSIndex(self.embedder.dimension)
        self.episode_ids: list[str] = []
        self.text_hashes: set[str] = set()
        if self.index_path.exists() and self.metadata_path.exists():
            self.load()

    def _text_for(self, record: dict[str, Any]) -> str:
        subject = record["subject"]
        event = record["event"]
        return f"{subject.get('domain', '')} {subject.get('task_id', '')}\n{event.get('output', '')}"

    def add_records(self, records: Sequence[dict[str, Any]]) -> int:
        pending: list[dict[str, Any]] = []
        texts: list[str] = []
        for raw in records:
            record = validate_record(raw)
            text = self._text_for(record)
            text_hash = compute_content_hash({"text": text})
            if record["memory_id"] in self.episode_ids or text_hash in self.text_hashes:
                continue
            pending.append(record)
            texts.append(text)
        if not pending:
            return 0
        vectors = self.embedder.encode(texts)
        self.faiss_index.add(vectors)
        self.episode_ids.extend(record["memory_id"] for record in pending)
        self.text_hashes.update(compute_content_hash({"text": text}) for text in texts)
        self.save()
        return len(pending)

    def rebuild(self, limit: int | None = None) -> int:
        records = list(self.store.iter_ordered())
        if limit is not None:
            records = records[-max(1, int(limit)):]
        self.faiss_index = type(self.faiss_index)(self.embedder.dimension)
        self.episode_ids = []
        self.text_hashes = set()
        return self.add_records(records)

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if not self.episode_ids:
            return []
        query_vector = self.embedder.encode([query])
        distances, indices = self.faiss_index.search(query_vector, min(max(1, k), len(self.episode_ids)))
        results: list[dict[str, Any]] = []
        for rank, (distance, index) in enumerate(zip(distances[0], indices[0]), start=1):
            if int(index) < 0 or int(index) >= len(self.episode_ids):
                continue
            memory_id = self.episode_ids[int(index)]
            record = self.store.get(memory_id)
            if record is not None:
                results.append({"memory_id": memory_id, "score": float(distance), "rank": rank, "record": record})
        return results

    def save(self) -> None:
        self.faiss_index.save(self.index_path)
        self.metadata_path.write_text(
            json.dumps({"episode_ids": self.episode_ids, "text_hashes": sorted(self.text_hashes)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load(self) -> None:
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        ids = metadata.get("episode_ids")
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise EpisodicMemoryError("metadata FAISS inválida")
        self.faiss_index.load(self.index_path)
        if self.faiss_index.ntotal != len(ids):
            raise EpisodicMemoryError("quantidade de vetores FAISS diverge do metadata")
        self.episode_ids = ids
        self.text_hashes = set(metadata.get("text_hashes", []))

    def close(self) -> None:
        flush = getattr(self.embedder, "flush_cache", None)
        if callable(flush):
            flush()
