#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔱 ATENA Corporate Memory & RAG Engine v3.0 - Memória Corporativa com Governança Avançada
Sistema completo de memória organizacional com RAG, governança e auditoria.

Recursos:
- 🧠 RAG (Retrieval-Augmented Generation) com múltiplas estratégias
- 🛡️ Governança por classificação (niveis de acesso, retenção)
- 📊 Métricas de uso e performance
- 🔍 Busca semântica com embeddings e BM25
- 📝 Auditoria completa de acesso e modificações
- 🔄 Rotação e expiração automática de memórias
- 🔒 Redação automática de segredos
- 🌐 Suporte a múltiplos tenants
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from collections import Counter, OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import threading

# Tentativa de importar bibliotecas avançadas
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

try:
    import torch
    torch.set_num_threads(int(os.getenv("ATENA_TORCH_THREADS", "1")))
    torch.set_num_interop_threads(int(os.getenv("ATENA_TORCH_INTEROP_THREADS", "1")))
except (ImportError, RuntimeError, ValueError):
    torch = None

logger = logging.getLogger(__name__)


# =============================================================================
# Constantes e Configurações
# =============================================================================

class ClassificationLevel(Enum):
    """Níveis de classificação para governança."""
    PUBLIC = "public"           # Acesso público
    INTERNAL = "internal"       # Uso interno
    CONFIDENTIAL = "confidential"  # Confidencial
    RESTRICTED = "restricted"   # Altamente restrito
    SECRET = "secret"           # Secreto


class AccessLevel(Enum):
    """Níveis de acesso para diferentes roles."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    AUDIT = "audit"


# Padrões de segredos para redação
SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{18,}"), "GITHUB_TOKEN"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"), "GITHUB_PAT"),
    (re.compile(r"sk-[A-Za-z0-9]{30,}"), "OPENAI_KEY"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{30,}"), "ANTHROPIC_KEY"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS_ACCESS_KEY"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "GOOGLE_API_KEY"),
    (re.compile(r"xox[bap]-[0-9A-Za-z\-]{30,}"), "SLACK_TOKEN"),
    (re.compile(r"-----BEGIN.*PRIVATE KEY-----"), "PRIVATE_KEY"),
]


@dataclass
class MemoryEntry:
    """Entrada de memória estruturada."""
    id: Optional[int]
    tenant_id: str
    content: str
    citation: str
    classification: str
    tags: List[str]
    created_at: str
    updated_at: str
    access_count: int = 0
    last_accessed: Optional[str] = None
    source: Optional[str] = None
    embedding: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "content": self.content[:500],
            "citation": self.citation,
            "classification": self.classification,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "source": self.source,
            "metadata": self.metadata
        }


@dataclass
class QueryResult:
    """Resultado de consulta RAG."""
    content: str
    citation: str
    classification: str
    tags: List[str]
    score: float
    semantic_score: float
    bm25_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content[:500],
            "citation": self.citation,
            "classification": self.classification,
            "tags": self.tags,
            "score": round(self.score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "bm25_score": round(self.bm25_score, 4)
        }


# =============================================================================
# Utilitários
# =============================================================================

def redact_secrets(text: str) -> str:
    """Redige segredos no texto."""
    redacted = text
    for pattern, label in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def tokenize(text: str) -> Set[str]:
    """Tokeniza texto para BM25."""
    return {t for t in re.split(r"\W+", text.lower()) if len(t) > 2 and not t.isdigit()}


def compute_tfidf(tokens: Set[str], all_tokens: List[Set[str]]) -> Dict[str, float]:
    """Calcula TF-IDF para tokens."""
    doc_freq = defaultdict(int)
    for doc_tokens in all_tokens:
        for token in set(doc_tokens):
            doc_freq[token] += 1
    
    n_docs = len(all_tokens)
    tfidf = {}
    for token in tokens:
        tf = 1.0  # Term frequency simplificada
        idf = math.log((n_docs + 1) / (doc_freq.get(token, 1) + 1)) + 1
        tfidf[token] = tf * idf
    
    return tfidf


# =============================================================================
# BM25 Search Engine
# =============================================================================

class BM25:
    """BM25 com índice invertido e frequências documentais pré-calculadas.

    O índice mantém postings ``token -> {doc_id: term_frequency}``. A busca
    pontua somente documentos que contêm ao menos um token da consulta, em
    vez de recalcular ``doc_freq`` e visitar todos os documentos.
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: List[str] = []  # mantido por compatibilidade; não é usado no scoring
        self.n_docs: int = 0
        self.doc_lengths: List[int] = []
        self.postings: Dict[str, List[Tuple[int, int]]] = {}
        self._doc_freq: Dict[str, int] = {}
        self.avgdl: float = 0.0
    
    def index(self, corpus: List[str]):
        """Indexa corpus para BM25."""
        self.corpus = []
        self.n_docs = len(corpus)
        self.doc_lengths = []
        self.postings = defaultdict(list)
        for doc_idx, doc in enumerate(corpus):
            counts = Counter(re.split(r"\W+", doc.lower()))
            counts = Counter({token: count for token, count in counts.items()
                              if len(token) > 2 and not token.isdigit()})
            self.doc_lengths.append(sum(counts.values()))
            for token, term_frequency in counts.items():
                self.postings[token].append((doc_idx, term_frequency))
        self.postings = dict(self.postings)
        self._doc_freq = {token: len(documents) for token, documents in self.postings.items()}
        self.avgdl = sum(self.doc_lengths) / max(1, self.n_docs)
    
    def score(self, query: str, doc_idx: int) -> float:
        """Calcula score BM25 para um documento."""
        query_tokens = tokenize(query)
        doc_len = self.doc_lengths[doc_idx]
        
        score = 0.0
        for token in query_tokens:
            tf = next((tf for candidate, tf in self.postings.get(token, [])
                       if candidate == doc_idx), 0)
            if tf == 0:
                continue
            
            idf = math.log((self.n_docs - self.doc_freq(token) + 0.5) /
                           (self.doc_freq(token) + 0.5) + 1)
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl))
            score += idf * tf_norm
        
        return score
    
    def doc_freq(self, token: str) -> int:
        """Frequência de documentos contendo o token em O(1)."""
        return self._doc_freq.get(token, 0)
    
    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """Busca por BM25."""
        query_tokens = tokenize(query)
        scores: Dict[int, float] = defaultdict(float)
        for token in query_tokens:
            doc_freq = self.doc_freq(token)
            if not doc_freq:
                continue
            idf = math.log((self.n_docs - doc_freq + 0.5) /
                           (doc_freq + 0.5) + 1)
            for doc_idx, tf in self.postings[token]:
                doc_len = self.doc_lengths[doc_idx]
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                )
                scores[doc_idx] += idf * tf_norm
        ranked = list(scores.items())
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# =============================================================================
# Tenant Memory RAG Avançado
# =============================================================================

class TenantMemoryRAG:
    """
    Sistema de memória corporativa com RAG e governança.
    Suporta busca semântica, BM25, classificações e auditoria.
    """
    
    def __init__(
        self,
        db_path: str | Path,
        embedding_model: Optional[str] = "all-MiniLM-L6-v2",
        enable_embeddings: bool = True
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.enable_embeddings = enable_embeddings and HAS_EMBEDDINGS
        self.lexical_engine = os.getenv("ATENA_LEXICAL_ENGINE", "bm25").lower()
        lexical_path = os.getenv("ATENA_FTS5_DB_PATH")
        self.fts5_db_path = Path(lexical_path) if lexical_path else None
        self.embedding_model = None
        self.bm25_indexes: Dict[str, BM25] = {}
        self._bm25_rows: Dict[str, List[Tuple[Any, ...]]] = {}
        self._retrieval_rows_cache: Dict[str, List[Tuple[Any, ...]]] = {}
        self._query_embedding_cache: OrderedDict[str, bytes] = OrderedDict()
        self._query_embedding_cache_max = int(os.getenv("ATENA_QUERY_EMBEDDING_CACHE_SIZE", "4096"))
        self._normalize_embeddings = os.getenv("ATENA_NORMALIZE_EMBEDDINGS", "1") == "1"
        self._cache: Dict[str, List[QueryResult]] = {}
        self._lock = threading.RLock()
        # SQLite aceita muitos leitores, mas apenas um escritor por vez.
        # Serializar as escritas dentro do processo evita tempestades de lock
        # quando várias threads atualizam acesso e auditoria simultaneamente.
        self._write_lock = threading.Lock()
        self._write_retries = 6
        self._write_backoff_seconds = 0.02
        self._audit_publisher = None
        if os.getenv("ATENA_ASYNC_AUDIT", "0") == "1":
            try:
                import redis
                from core.atena_audit_queue import make_query_event, publish_event

                client = redis.Redis.from_url(
                    os.getenv("ATENA_REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                    socket_timeout=1.5,
                    socket_connect_timeout=1.5,
                )
                self._audit_publisher = (client, make_query_event, publish_event)
            except Exception as exc:
                logger.warning("Auditoria Redis assíncrona indisponível: %s", exc)
        
        if self.enable_embeddings:
            try:
                self.embedding_model = SentenceTransformer(embedding_model)
                logger.info(f"Modelo de embeddings carregado: {embedding_model}")
            except Exception as e:
                logger.warning(f"Falha ao carregar modelo de embeddings: {e}")
                self.enable_embeddings = False
        
        self._init_db()
        self._load_bm25_indexes()
    
    def _init_db(self) -> None:
        """Inicializa banco de dados com tabelas otimizadas."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory (
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
                    metadata_json TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_tenant_class ON memory(tenant_id, classification);
                CREATE INDEX IF NOT EXISTS idx_created_at ON memory(created_at);
                CREATE INDEX IF NOT EXISTS idx_access_count ON memory(access_count DESC);
                CREATE INDEX IF NOT EXISTS idx_tags ON memory(tags_json);
                
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    memory_id INTEGER,
                    user_id TEXT,
                    timestamp TEXT NOT NULL,
                    details_json TEXT,
                    event_id TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
            if "event_id" not in columns:
                conn.execute("ALTER TABLE audit_log ADD COLUMN event_id TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_id "
                "ON audit_log(event_id) WHERE event_id IS NOT NULL"
            )
            if self.lexical_engine == "fts5" and self.fts5_db_path is None:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                        content,
                        content='memory',
                        content_rowid='id',
                        tokenize='unicode61 remove_diacritics 2'
                    );
                    CREATE TRIGGER IF NOT EXISTS memory_fts_ai
                    AFTER INSERT ON memory BEGIN
                        INSERT INTO memory_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_au
                    AFTER UPDATE OF content ON memory BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                        INSERT INTO memory_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_ad
                    AFTER DELETE ON memory BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                    END;
                    """
                )
            conn.commit()
    
    def _connect(self) -> sqlite3.Connection:
        """Retorna conexão com o banco."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _read_connect(self) -> sqlite3.Connection:
        """Abre uma conexão somente leitura para o caminho quente da consulta."""
        conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, timeout=30.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _lexical_connect(self) -> sqlite3.Connection:
        """Abre o índice FTS5 separado em modo somente leitura."""
        path = self.fts5_db_path or self.db_path
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, timeout=30.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA cache_size=-131072")
        mmap_size = int(os.getenv("ATENA_FTS5_MMAP_SIZE", str(1024 * 1024 * 1024)))
        conn.execute(f"PRAGMA mmap_size={mmap_size}")
        return conn

    def _run_write(self, operation: Any) -> Any:
        """Executa uma operação de escrita com lock local e retry exponencial.

        O lock cobre apenas o processo atual. Em múltiplos processos, o
        ``busy_timeout`` e o retry continuam protegendo contra locks breves.
        """
        delay = self._write_backoff_seconds
        last_error: Optional[Exception] = None
        for attempt in range(self._write_retries):
            try:
                with self._write_lock:
                    return operation()
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                last_error = exc
                if attempt == self._write_retries - 1:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
        assert last_error is not None
        raise last_error
    
    def _log_audit(
        self,
        tenant_id: str,
        action: str,
        memory_id: Optional[int] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict] = None,
        event_id: Optional[str] = None,
    ) -> None:
        """Registra ação no log de auditoria."""
        def insert() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log
                        (tenant_id, action, memory_id, user_id, timestamp, details_json, event_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        action,
                        memory_id,
                        user_id or "system",
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(details or {}),
                        event_id,
                    )
                )
                conn.commit()
        self._run_write(insert)
    
    def _generate_embedding(self, text: str) -> Optional[bytes]:
        """Gera embedding para texto."""
        if not self.enable_embeddings or not self.embedding_model:
            return None
        cache_key = hashlib.sha256(text[:1000].strip().lower().encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._query_embedding_cache.get(cache_key)
            if cached is not None:
                self._query_embedding_cache.move_to_end(cache_key)
                return cached
        try:
            embedding = self.embedding_model.encode(
                text[:1000], normalize_embeddings=self._normalize_embeddings
            ).astype(np.float32)
            encoded = embedding.tobytes()
            with self._lock:
                self._query_embedding_cache[cache_key] = encoded
                self._query_embedding_cache.move_to_end(cache_key)
                while len(self._query_embedding_cache) > self._query_embedding_cache_max:
                    self._query_embedding_cache.popitem(last=False)
            return encoded
        except Exception as e:
            logger.debug(f"Erro ao gerar embedding: {e}")
            return None
    
    def _compute_cosine_similarity(self, emb1: bytes, emb2: bytes) -> float:
        """Calcula similaridade de cosseno entre embeddings."""
        if not HAS_NUMPY:
            return 0.0
        try:
            a = np.frombuffer(emb1, dtype=np.float32)
            b = np.frombuffer(emb2, dtype=np.float32)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            if self._normalize_embeddings:
                return float(np.dot(a, b))
            return float(np.dot(a, b) / (norm_a * norm_b))
        except Exception:
            return 0.0
    
    def _load_bm25_indexes(self) -> None:
        """Mantém os índices lazy; não carrega o corpus inteiro no startup."""
        self.bm25_indexes.clear()
        self._bm25_rows.clear()

    def _get_bm25_index(
        self,
        tenant_id: str,
        rows: List[Tuple[Any, ...]],
        classification: Optional[str],
        tags: Optional[List[str]],
    ) -> Tuple[BM25, List[Tuple[Any, ...]]]:
        """Reuse a BM25 index for an equivalent tenant/filter scope."""
        filter_key = f"{tenant_id}:{classification}:{','.join(sorted(tags or []))}"
        if filter_key not in self.bm25_indexes:
            bm25_rows = rows
            bm25 = BM25()
            bm25.index([row[1] for row in bm25_rows])
            self.bm25_indexes[filter_key] = bm25
            self._bm25_rows[filter_key] = bm25_rows
        return self.bm25_indexes[filter_key], self._bm25_rows[filter_key]
    
    def _rebuild_bm25_index(self, tenant_id: str) -> None:
        """Reconstrói índice BM25 para um tenant."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT content FROM memory WHERE tenant_id=?",
                (tenant_id,)
            ).fetchall()
            if rows:
                bm25 = BM25()
                bm25.index([r[0] for r in rows])
                self.bm25_indexes[tenant_id] = bm25

    @staticmethod
    def _fts5_query(text: str) -> str:
        """Converte texto livre em uma expressão FTS5 sem operadores ativos."""
        stopwords = {"como", "qual", "quais", "para", "com", "sem", "uma", "das", "dos", "que", "por", "sobre"}
        tokens = list(dict.fromkeys(token for token in re.split(r"\W+", text.lower())
                                   if len(token) > 2 and not token.isdigit() and token not in stopwords))
        return " AND ".join('"' + token.replace('"', '') + '"' for token in tokens)

    @staticmethod
    def _fts5_tokens(text: str) -> List[str]:
        expression = TenantMemoryRAG._fts5_query(text)
        return re.findall(r'"([^\"]+)"', expression)

    @staticmethod
    def _fts5_expression(tokens: List[str], operator: str) -> str:
        return f" {operator} ".join('"' + token.replace('"', '') + '"' for token in tokens)

    def _search_fts5(
        self,
        tenant_id: str,
        question: str,
        top_k: int,
        classification: Optional[str],
        tags: Optional[List[str]],
    ) -> Tuple[List[Tuple[Any, ...]], List[Tuple[int, float]]]:
        """Retorna somente candidatos FTS5 e seus scores lexicais."""
        tokens = self._fts5_tokens(question)
        if not tokens:
            return [], []
        target = max(top_k * 4, top_k)
        fetched = []
        with self._lexical_connect() as lexical:
            for mode, attempt_tokens in (("and", tokens), ("or", tokens), ("informative_or", tokens[:4])):
                if not attempt_tokens:
                    continue
                expression = self._fts5_expression(attempt_tokens, "AND" if mode == "and" else "OR")
                if self.fts5_db_path:
                    query = "SELECT memory_id, bm25(memory_fts) FROM memory_fts WHERE memory_fts MATCH ? AND tenant_id=?"
                    params: List[Any] = [expression, tenant_id]
                    if classification:
                        query += " AND classification=?"
                        params.append(classification)
                    query += " ORDER BY 2 LIMIT ?"
                    params.append(target)
                else:
                    query = "SELECT rowid, bm25(memory_fts) FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?"
                    params = [expression, target]
                fetched = lexical.execute(query, params).fetchall()
                if fetched:
                    break
        if not fetched:
            return [], []
        ids = [int(row[0]) for row in fetched]
        placeholders = ",".join("?" for _ in ids)
        with self._read_connect() as conn:
            rows = conn.execute(
                f"SELECT id, content, citation, classification, tags_json, created_at, updated_at, access_count, embedding FROM memory WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        by_id = {row[0]: row for row in rows}
        if tags:
            wanted = set(tags)
            ids = [memory_id for memory_id in ids if memory_id in by_id and wanted.intersection(set(json.loads(by_id[memory_id][4])))]
        rows = [by_id[memory_id] for memory_id in ids if memory_id in by_id]
        scores = [
            (int(memory_id), 1.0 / (1.0 + max(0.0, -float(raw_score))))
            for memory_id, raw_score in fetched if int(memory_id) in by_id
        ]
        return rows, scores
    
    def upsert(
        self,
        tenant_id: str,
        content: str,
        citation: str,
        classification: str = "internal",
        tags: List[str] | None = None,
        source: Optional[str] = None,
        metadata: Optional[Dict] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Insere ou atualiza entrada de memória.
        
        Args:
            tenant_id: Identificador do tenant
            content: Conteúdo da memória
            citation: Fonte/citação
            classification: Nível de classificação
            tags: Tags para categorização
            source: Fonte original
            metadata: Metadados adicionais
            user_id: ID do usuário (para auditoria)
        """
        now = datetime.now(timezone.utc).isoformat()
        tags = tags or []
        metadata = metadata or {}
        
        # Redige segredos
        content_redacted = redact_secrets(content)
        citation_redacted = redact_secrets(citation)
        
        # Gera embedding
        embedding = self._generate_embedding(content_redacted)
        
        with self._connect() as conn:
            # Verifica duplicata por content hash
            content_hash = hashlib.md5(content_redacted.encode()).hexdigest()
            existing = conn.execute(
                "SELECT id FROM memory WHERE tenant_id=? AND content_hash=?",
                (tenant_id, content_hash)
            ).fetchone() if 'content_hash' in [c[1] for c in conn.execute("PRAGMA table_info(memory)").fetchall()] else None
            
            # Adiciona coluna content_hash se não existir
            try:
                conn.execute("ALTER TABLE memory ADD COLUMN content_hash TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON memory(content_hash)")
            except sqlite3.OperationalError:
                pass
            
            if existing:
                # Atualiza existente
                conn.execute(
                    """
                    UPDATE memory
                    SET content=?, citation=?, classification=?, tags_json=?,
                        updated_at=?, source=?, metadata_json=?, embedding=?
                    WHERE id=?
                    """,
                    (
                        content_redacted, citation_redacted, classification,
                        json.dumps(tags), now, source, json.dumps(metadata),
                        embedding, existing[0]
                    )
                )
                memory_id = existing[0]
                action = "update"
            else:
                # Insere novo
                result = conn.execute(
                    """
                    INSERT INTO memory
                    (tenant_id, content, citation, classification, tags_json,
                     created_at, updated_at, source, metadata_json, embedding, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id, content_redacted, citation_redacted, classification,
                        json.dumps(tags), now, now, source, json.dumps(metadata),
                        embedding, content_hash
                    )
                )
                memory_id = result.lastrowid
                action = "insert"
            
            conn.commit()
        
        # Reconstrói índice BM25
        self._rebuild_bm25_index(tenant_id)
        
        # Limpa cache
        with self._lock:
            self._cache.pop(tenant_id, None)
            for key in list(self.bm25_indexes):
                if key == tenant_id or key.startswith(f"{tenant_id}:"):
                    self.bm25_indexes.pop(key, None)
                    self._bm25_rows.pop(key, None)
            for key in list(self._retrieval_rows_cache):
                if key.startswith(f"{tenant_id}:"):
                    self._retrieval_rows_cache.pop(key, None)
        
        # Log de auditoria
        self._log_audit(tenant_id, action, memory_id, user_id, {
            "classification": classification,
            "tags": tags,
            "source": source
        })
        
        return {
            "status": "ok",
            "action": action,
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "classification": classification,
            "created_at": now if action == "insert" else None,
            "updated_at": now,
            "citation": citation_redacted[:200]
        }
    
    def query(
        self,
        tenant_id: str,
        question: str,
        top_k: int = 5,
        classification: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_score: float = 0.1,
        use_cache: bool = True,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Consulta memórias usando RAG (BM25 + semantic search).
        
        Args:
            tenant_id: Identificador do tenant
            question: Pergunta/consulta
            top_k: Número de resultados
            classification: Filtrar por classificação
            tags: Filtrar por tags
            min_score: Score mínimo para retornar
            use_cache: Usar cache de resultados
            user_id: ID do usuário (para auditoria)
        """
        # Verifica cache
        cache_key = f"{tenant_id}:{question}:{classification}:{str(tags)}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            # Cache válido por 5 minutos
            if cached and (datetime.now() - timedelta(minutes=5)).isoformat() < cached[0].updated_at:
                results = cached
            else:
                with self._lock:
                    self._cache.pop(cache_key, None)
                results = []
        else:
            results = []
        
        if not results:
            if self.lexical_engine == "fts5":
                rows, bm25_results = self._search_fts5(
                    tenant_id, question, top_k, classification, tags
                )
                indexed_rows = rows
                fts_rows_by_id = {row[0]: row for row in rows}
            else:
                filter_key = f"{tenant_id}:{classification}:{','.join(sorted(tags or []))}"
                with self._lock:
                    rows = self._retrieval_rows_cache.get(filter_key)
                if rows is None:
                    # Fallback BM25: preserva o comportamento legado.
                    with self._read_connect() as conn:
                        query = """
                            SELECT id, content, citation, classification, tags_json,
                                   created_at, updated_at, access_count, embedding
                            FROM memory WHERE tenant_id=?
                        """
                        params = [tenant_id]
                        if classification:
                            query += " AND classification=?"
                            params.append(classification)
                        rows = conn.execute(query, params).fetchall()
                    if tags:
                        tag_set = set(tags)
                        rows = [row for row in rows
                                if tag_set.intersection(set(json.loads(row[4])))]
                    with self._lock:
                        self._retrieval_rows_cache[filter_key] = rows

            if not rows:
                return {
                    "status": "ok",
                    "tenant_id": tenant_id,
                    "question": question,
                    "results": [],
                    "total_found": 0,
                    "citations_required": True,
                }
            
            if self.lexical_engine != "fts5":
                bm25, indexed_rows = self._get_bm25_index(
                    tenant_id, rows, classification, tags
                )
                bm25_results = [
                    (indexed_rows[idx][0], score)
                    for idx, score in bm25.search(question, top_k * 2)
                ]
            
            # Prepara embeddings para busca semântica
            embeddings_dict = {}
            if self.enable_embeddings:
                for row in rows:
                    if row[8]:  # embedding
                        embeddings_dict[row[0]] = row[8]
                
                # Gera embedding da query
                query_embedding = self._generate_embedding(question)
            
            # Combina scores
            scored_results = []
            for memory_id, bm25_score in bm25_results:
                row = (fts_rows_by_id if self.lexical_engine == "fts5" else
                       {candidate[0]: candidate for candidate in indexed_rows})[memory_id]
                content = row[1]
                citation = row[2]
                classification_val = row[3]
                tags_val = json.loads(row[4])
                created_at = row[5]
                updated_at = row[6]
                access_count = row[7]
                
                # Score BM25 (normalizado)
                bm25_norm = min(1.0, bm25_score)
                
                # Score semântico
                semantic_score = 0.0
                if self.enable_embeddings and query_embedding and memory_id in embeddings_dict:
                    semantic_score = self._compute_cosine_similarity(
                        query_embedding, embeddings_dict[memory_id]
                    )
                
                # Score combinado
                combined_score = (bm25_norm * 0.4 + semantic_score * 0.6)
                
                if combined_score >= min_score:
                    scored_results.append({
                        "content": content,
                        "citation": citation,
                        "classification": classification_val,
                        "tags": tags_val,
                        "bm25_score": bm25_norm,
                        "semantic_score": semantic_score,
                        "combined_score": combined_score,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "access_count": access_count,
                        "memory_id": memory_id
                    })
            
            # Ordena por score combinado
            scored_results.sort(key=lambda x: x["combined_score"], reverse=True)
            results = scored_results[:top_k]
            
            # Atualiza cache
            with self._lock:
                self._cache[cache_key] = results
        
        # Atualiza contadores de acesso
        if self._audit_publisher is not None:
            client, make_query_event, publish_event = self._audit_publisher
            event = make_query_event(
                tenant_id=tenant_id,
                question=question,
                memory_ids=[int(r["memory_id"]) for r in results],
                user_id=user_id,
                results_count=len(results),
            )
            try:
                publish_event(client, event)
            except Exception:
                logger.exception("Falha ao publicar auditoria Redis; usando escrita síncrona")
                self._audit_publisher = None
            else:
                return self._format_query_response(
                    tenant_id, question, results
                )

        for r in results:
            def update_access(memory_id: int = r["memory_id"]) -> None:
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE memory SET access_count=access_count+1, last_accessed=? WHERE id=?",
                        (datetime.now(timezone.utc).isoformat(), memory_id)
                    )
                    conn.commit()
            self._run_write(update_access)

        self._log_audit(tenant_id, "query", user_id=user_id, details={
            "question": question[:200],
            "classification_filter": classification,
            "tags_filter": tags,
            "results_count": len(results)
        })
        
        return self._format_query_response(tenant_id, question, results)

    def _format_query_response(
        self,
        tenant_id: str,
        question: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Formata uma resposta já recuperada sem executar efeitos de escrita."""
        formatted_results = [
            QueryResult(
                content=r["content"],
                citation=r["citation"],
                classification=r["classification"],
                tags=r["tags"],
                score=r["combined_score"],
                semantic_score=r["semantic_score"],
                bm25_score=r["bm25_score"]
            ) for r in results
        ]
        
        return {
            "status": "ok",
            "tenant_id": tenant_id,
            "question": question,
            "results": [r.to_dict() for r in formatted_results],
            "total_found": len(formatted_results),
            "citations_required": True,
            "semantic_search_enabled": self.enable_embeddings,
            "bm25_enabled": True
        }
    
    def delete(
        self,
        tenant_id: str,
        memory_id: int,
        user_id: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Remove entrada de memória."""
        with self._connect() as conn:
            # Verifica existência
            row = conn.execute(
                "SELECT content FROM memory WHERE id=? AND tenant_id=?",
                (memory_id, tenant_id)
            ).fetchone()
            
            if not row:
                return {"status": "error", "error": "Memory entry not found"}
            
            # Remove
            conn.execute("DELETE FROM memory WHERE id=?", (memory_id,))
            conn.commit()
        
        # Reconstrói índice
        self._rebuild_bm25_index(tenant_id)
        
        # Limpa cache
        with self._lock:
            self._cache.clear()
        
        # Log de auditoria
        self._log_audit(tenant_id, "delete", memory_id, user_id, {"reason": reason})
        
        return {
            "status": "ok",
            "action": "delete",
            "memory_id": memory_id,
            "tenant_id": tenant_id
        }
    
    def purge_expired(self, retention_days: Dict[str, int]) -> Dict[str, Any]:
        """
        Remove memórias expiradas baseado em política de retenção.
        
        Args:
            retention_days: Dict com retenção por classificação,
                           ex: {"internal": 90, "confidential": 30, "default": 365}
        """
        now = datetime.now(timezone.utc)
        deleted = 0
        deleted_details = []
        
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, classification, created_at, tenant_id FROM memory"
            ).fetchall()
            
            for row_id, classification, created_at, tenant_id in rows:
                retention = retention_days.get(classification, retention_days.get("default", 365))
                try:
                    created = datetime.fromisoformat(created_at)
                except ValueError:
                    created = now
                
                if created < now - timedelta(days=retention):
                    conn.execute("DELETE FROM memory WHERE id=?", (row_id,))
                    deleted += 1
                    deleted_details.append({
                        "id": row_id,
                        "classification": classification,
                        "tenant_id": tenant_id,
                        "created_at": created_at
                    })
                    # Audit log é gravado após commit para evitar lock SQLite reentrante.
            
            conn.commit()

        for detail in deleted_details:
            self._log_audit(
                detail["tenant_id"],
                "auto_purge",
                detail["id"],
                details={"retention_days": retention_days.get(detail["classification"], retention_days.get("default", 365)), "expired_at": detail["created_at"]},
            )
        
        # Reconstrói índices afetados
        tenants_affected = set(d["tenant_id"] for d in deleted_details)
        for tenant_id in tenants_affected:
            self._rebuild_bm25_index(tenant_id)
        
        # Limpa cache
        with self._lock:
            self._cache.clear()
        
        return {
            "status": "ok",
            "deleted": deleted,
            "deleted_details": deleted_details[:10],
            "retention_policy": retention_days
        }
    
    def get_statistics(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Retorna estatísticas do sistema."""
        stats = {
            "total_entries": 0,
            "by_classification": defaultdict(int),
            "by_tag": defaultdict(int),
            "avg_access_count": 0.0,
            "total_accesses": 0,
            "last_7_days_queries": 0
        }
        
        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT classification, tags_json, access_count FROM memory WHERE tenant_id=?",
                    (tenant_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT classification, tags_json, access_count FROM memory"
                ).fetchall()
            
            stats["total_entries"] = len(rows)
            total_accesses = 0
            
            for classification, tags_json, access_count in rows:
                stats["by_classification"][classification] += 1
                total_accesses += access_count
                
                for tag in json.loads(tags_json):
                    stats["by_tag"][tag] += 1
            
            if stats["total_entries"] > 0:
                stats["avg_access_count"] = total_accesses / stats["total_entries"]
            stats["total_accesses"] = total_accesses
            
            # Consultas nos últimos 7 dias
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            stats["last_7_days_queries"] = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action='query' AND timestamp > ?",
                (week_ago,)
            ).fetchone()[0]
        
        # Converte defaultdicts para dict
        stats["by_classification"] = dict(stats["by_classification"])
        stats["by_tag"] = dict(sorted(stats["by_tag"].items(), key=lambda x: x[1], reverse=True)[:20])
        
        return stats
    
    def get_audit_log(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retorna log de auditoria."""
        with self._connect() as conn:
            query = "SELECT id, tenant_id, action, memory_id, user_id, timestamp, details_json FROM audit_log"
            params = []
            
            conditions = []
            if tenant_id:
                conditions.append("tenant_id=?")
                params.append(tenant_id)
            if action:
                conditions.append("action=?")
                params.append(action)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            return [
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "action": row[2],
                    "memory_id": row[3],
                    "user_id": row[4],
                    "timestamp": row[5],
                    "details": json.loads(row[6]) if row[6] else {}
                }
                for row in rows
            ]


# =============================================================================
# Reasoning Trace Builder (Compatibilidade com código original)
# =============================================================================

def build_reasoning_trace(steps: List[str], citations: List[str]) -> Dict[str, Any]:
    """
    Constrói trilha de raciocínio para auditoria e transparência.
    """
    redacted_steps = [redact_secrets(step) for step in steps]
    missing = [i for i, c in enumerate(citations) if not c]
    
    return {
        "status": "ok" if not missing else "warn",
        "steps": redacted_steps,
        "citations": citations,
        "citations_required": len(missing) == 0,
        "missing_citation_indexes": missing,
        "total_steps": len(steps),
        "complete_citations": sum(1 for c in citations if c)
    }


# =============================================================================
# Instância global para uso em toda a aplicação
# =============================================================================

_default_memory: Optional[TenantMemoryRAG] = None


def get_memory_instance(db_path: str | Path = "atena_evolution/corporate_memory.db") -> TenantMemoryRAG:
    """Retorna instância global do sistema de memória."""
    global _default_memory
    if _default_memory is None:
        _default_memory = TenantMemoryRAG(db_path)
    return _default_memory


# =============================================================================
# CLI e Demonstração
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="ATENA Corporate Memory & RAG Engine")
    parser.add_argument("--init", action="store_true", help="Inicializa banco de dados")
    parser.add_argument("--stats", action="store_true", help="Mostra estatísticas")
    parser.add_argument("--query", type=str, help="Faz uma consulta RAG")
    parser.add_argument("--tenant", type=str, default="default", help="Tenant ID")
    parser.add_argument("--classification", type=str, help="Filtrar por classificação")
    
    args = parser.parse_args()
    
    memory = get_memory_instance()
    
    if args.init:
        print("✅ Banco de memória inicializado")
        return 0
    
    if args.stats:
        stats = memory.get_statistics(args.tenant)
        print(json.dumps(stats, indent=2, default=str))
        return 0
    
    if args.query:
        result = memory.query(
            tenant_id=args.tenant,
            question=args.query,
            classification=args.classification
        )
        print(f"\n🔍 Resultados para: {args.query}")
        print("=" * 60)
        for i, r in enumerate(result["results"], 1):
            print(f"\n{i}. [Score: {r['score']:.2%}]")
            print(f"   {r['content'][:200]}...")
            print(f"   📎 {r['citation']}")
            if r['tags']:
                print(f"   🏷️ Tags: {', '.join(r['tags'])}")
        return 0
    
    print("Use --help para ver opções disponíveis")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
