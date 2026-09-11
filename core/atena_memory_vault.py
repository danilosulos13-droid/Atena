#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ATENA MEMORY VAULT v3.1.0                                  ║
║              Sistema Avançado de Versionamento de Modelos de IA              ║
║                                                                                ║
║  Features:                                                                    ║
║  • Compressão adaptativa com múltiplos codecs                                 ║
║  • Checksum criptográfico com SHA-256/Blake2b/xxHash                          ║
║  • Cache local LRU + cache distribuído opcional (Redis)                       ║
║  • Operações atômicas com journaling e rotação periódica                      ║
║  • Backup incremental e diferencial                                           ║
║  • Recuperação automática com checkpoint                                      ║
║  • Métricas em tempo real com Prometheus                                      ║
║  • Sharding automático para grandes datasets (I/O assíncrono)                 ║
║  • API RESTful integrada                                                      ║
║  • Event sourcing simples (pub/sub assíncrono)                                ║
║                                                                                ║
║  Autor: ATENA Consciousness Engine                                            ║
║  Licença: Proprietária - Todos os direitos reservados                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

Changelog v3.1.0 (revisão de correção de bugs e robustez)
----------------------------------------------------------
- CORRIGIDO: bloco morto que abria file handles de shards sem nunca
  escrevê-los/fechá-los em save_model_async (vazamento de descritores).
- CORRIGIDO: o codec de compressão efetivamente usado agora é persistido
  em metadata.custom_metadata["codec"], então load_model_async descomprime
  com o codec correto (antes sempre assumia "zstandard").
- CORRIGIDO: CompressionCodec.decompress agora cobre todos os codecs que
  podem ser produzidos por compress()/AUTO (gzip, zlib, bz2, lzma, zstd).
- CORRIGIDO: AUTO agora reutiliza o resultado já comprimido da amostra
  quando ela é igual aos dados completos, evitando compressão dupla.
- CORRIGIDO: singletons (VaultDatabase / AtenaMemoryVault) deixaram de
  ser singletons globais — cada instância tem seu próprio estado, o que
  é essencial para testes que usam diretórios temporários distintos.
  Caso se queira uma instância "padrão" compartilhada, usar
  AtenaMemoryVault.get_default().
- CORRIGIDO: removido o "async with asyncio.Lock()" inútil (lock novo a
  cada chamada); substituído por um asyncio.Lock por instância que
  realmente serializa escritas quando necessário.
- CORRIGIDO: `model_path` agora é definido antes do bloco try que pode
  falhar, evitando NameError no except.
- CORRIGIDO: `_get_best_version_async` valida a métrica contra uma
  allowlist antes de interpolar na query SQL (evita injeção via `metric`).
- CORRIGIDO: shard_data agora roda em thread separada via
  `asyncio.to_thread` para não bloquear o event loop.
- CORRIGIDO: serialização de metadados usa um encoder customizado para
  sets/datetime/bytes compatível com orjson.
- CORRIGIDO: EventBus não recria um ThreadPoolExecutor a cada publish;
  usa um executor compartilhado e não bloqueia o event loop.
- CORRIGIDO: JournalManager agora suporta rotação periódica real e
  fecha o arquivo corretamente no shutdown / context manager.
- ADICIONADO: método `aclose()` / suporte a `async with` no
  AtenaMemoryVault para liberar conexões Redis, journal e thread pools.
- LIMPEZA: removidos imports não utilizados.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import gzip
import hashlib
import io
import lzma
import os
import pickle
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import uuid
import warnings
import zlib
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, DefaultDict, Dict, Final, Generic, Iterator,
    List, NewType, Optional, OrderedDict as OrderedDictType, Set, Tuple, TypeVar
)

T = TypeVar("T")

import aiofiles
import msgpack
import orjson
import structlog
import xxhash
import zstandard as zstd
from fastapi import FastAPI, HTTPException, Query
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

try:
    from redis import asyncio as aioredis
except ImportError:  # Redis é opcional
    aioredis = None  # type: ignore

# ─── Configuração de Ambiente ────────────────────────────────────────────────
warnings.filterwarnings('ignore', category=DeprecationWarning)
os.environ.setdefault('ATENA_ENV', 'production')

# ─── Structured Logging ──────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ─── Métricas Prometheus ─────────────────────────────────────────────────────
METRICS_PREFIX = "atena_memory_vault"

model_saves = Counter(f"{METRICS_PREFIX}_model_saves_total", "Total saves", ["status"])
model_loads = Counter(f"{METRICS_PREFIX}_model_loads_total", "Total loads", ["status"])
model_versions = Gauge(f"{METRICS_PREFIX}_model_versions", "Active versions")
storage_bytes = Gauge(f"{METRICS_PREFIX}_storage_bytes", "Total storage used")
cache_hits = Counter(f"{METRICS_PREFIX}_cache_hits_total", "Cache hits")
cache_misses = Counter(f"{METRICS_PREFIX}_cache_misses_total", "Cache misses")
compression_ratio_metric = Histogram(f"{METRICS_PREFIX}_compression_ratio", "Compression ratio")
operation_latency = Histogram(
    f"{METRICS_PREFIX}_operation_latency_seconds",
    "Operation latency",
    ["operation"]
)

# ─── Constantes ──────────────────────────────────────────────────────────────
BASE_DIR: Final[Path] = Path(os.getenv(
    "ATENA_VAULT_DIR",
    Path.home() / ".atena" / "evolution" / "knowledge" / "vault"
))

DEFAULT_MAX_VERSIONS: Final[int] = int(os.getenv("ATENA_MAX_VERSIONS", "100"))
DEFAULT_CACHE_TTL: Final[int] = int(os.getenv("ATENA_CACHE_TTL", "300"))
DEFAULT_COMPRESSION_LEVEL: Final[int] = int(os.getenv("ATENA_COMPRESSION_LEVEL", "6"))
DEFAULT_SHARD_SIZE_MB: Final[int] = int(os.getenv("ATENA_SHARD_SIZE_MB", "64"))
DEFAULT_JOURNAL_ROTATE_SECONDS: Final[int] = int(os.getenv("ATENA_JOURNAL_ROTATE_SECONDS", "3600"))
DEFAULT_REDIS_URL: Final[str] = os.getenv("ATENA_REDIS_URL", "redis://localhost:6379/0")
DEFAULT_SQLITE_FILENAME: Final[str] = "vault.db"

# Métricas permitidas para ordenação no SQLite (allowlist contra injeção).
ALLOWED_RANKING_METRICS: Final[Set[str]] = {
    "accuracy", "loss", "f1_score", "precision", "recall", "auc_roc",
    "validation_accuracy", "validation_loss",
}

# ─── Tipos Customizados ─────────────────────────────────────────────────────
ModelId = NewType('ModelId', str)
VersionId = NewType('VersionId', str)
Checksum = NewType('Checksum', str)
ShardId = NewType('ShardId', int)
JournalEntryId = NewType('JournalEntryId', str)


# ─── Schemas Pydantic ───────────────────────────────────────────────────────
class PerformanceMetrics(BaseModel):
    """Métricas detalhadas de performance com validação rigorosa."""
    inference_time_us: float = Field(0.0, ge=0)
    training_time_s: float = Field(0.0, ge=0)
    memory_usage_bytes: int = Field(0, ge=0)
    cpu_usage_percent: float = Field(0.0, ge=0, le=100)
    gpu_memory_bytes: int = Field(0, ge=0)
    throughput_samples_per_sec: float = Field(0.0, ge=0)
    latency_p50_us: float = Field(0.0, ge=0)
    latency_p95_us: float = Field(0.0, ge=0)
    latency_p99_us: float = Field(0.0, ge=0)

    @field_validator('latency_p99_us')
    @classmethod
    def validate_percentiles(cls, v, info):
        p50 = info.data.get('latency_p50_us')
        if p50 is not None and v < p50:
            raise ValueError('p99 deve ser >= p50')
        return v


class TrainingConfig(BaseModel):
    """Configuração de treinamento com validação de schema."""
    optimizer: str = "adam"
    learning_rate: float = Field(0.001, gt=0, le=1.0)
    batch_size: int = Field(32, gt=0, le=65536)
    epochs: int = Field(100, gt=0, le=1_000_000)
    early_stopping_patience: int = Field(10, ge=0)
    gradient_clip_norm: Optional[float] = Field(None, ge=0)
    scheduler: Optional[str] = None
    warmup_steps: int = Field(0, ge=0)
    mixed_precision: bool = False
    distributed: bool = False
    seed: int = Field(42, ge=0)

    model_config = ConfigDict(extra="allow")


class ModelMetadata(BaseModel):
    """Metadados enriquecidos com validação completa."""
    version: VersionId
    model_id: ModelId
    timestamp: datetime.datetime
    created_at_utc: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    loss: float = Field(..., ge=0)
    accuracy: float = Field(..., ge=0, le=1)
    validation_loss: Optional[float] = Field(None, ge=0)
    validation_accuracy: Optional[float] = Field(None, ge=0, le=1)
    f1_score: Optional[float] = Field(None, ge=0, le=1)
    precision: Optional[float] = Field(None, ge=0, le=1)
    recall: Optional[float] = Field(None, ge=0, le=1)
    auc_roc: Optional[float] = Field(None, ge=0, le=1)

    model_size_bytes: int = Field(0, ge=0)
    compressed_size_bytes: int = Field(0, ge=0)
    compression_ratio: float = Field(0.0, ge=0)

    checksum_sha256: Checksum = ""
    checksum_blake2b: Checksum = ""
    checksum_xxhash: Checksum = ""

    parent_version: Optional[VersionId] = None
    lineage: List[VersionId] = Field(default_factory=list)

    tags: Set[str] = Field(default_factory=set)
    labels: Dict[str, str] = Field(default_factory=dict)

    training_config: TrainingConfig = Field(default_factory=TrainingConfig)
    performance_metrics: Optional[PerformanceMetrics] = None

    framework_version: str = "3.1.0"
    python_version: str = Field(default=sys.version.split()[0])
    platform: str = Field(default=sys.platform)

    is_archived: bool = False
    is_corrupted: bool = False
    is_verified: bool = False

    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)

    @model_validator(mode='before')
    @classmethod
    def compute_derived_fields(cls, values):
        if isinstance(values, dict):
            size = values.get('model_size_bytes')
            compressed = values.get('compressed_size_bytes')
            if size and compressed is not None and size > 0:
                values['compression_ratio'] = compressed / size
        return values

    def to_jsonable(self) -> Dict[str, Any]:
        """Converte para um dict serializável por orjson (sets -> lists)."""
        data = self.model_dump()
        return _convert_sets(data)


def _convert_sets(obj: Any) -> Any:
    """Converte recursivamente sets em listas e datetimes em strings ISO,
    para serialização compatível com orjson e msgpack."""
    if isinstance(obj, dict):
        return {k: _convert_sets(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, list):
        return [_convert_sets(v) for v in obj]
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    return obj


# ─── Enums ───────────────────────────────────────────────────────────────────
class CompressionCodec(Enum):
    """Codecs de compressão suportados."""
    GZIP = "gzip"
    ZLIB = "zlib"
    BZ2 = "bz2"
    LZMA = "lzma"
    ZSTANDARD = "zstandard"
    AUTO = "auto"  # Seleciona automaticamente o melhor codec disponível

    def compress(self, data: bytes, level: int = 6) -> Tuple[bytes, "CompressionCodec"]:
        """Comprime `data` e retorna (bytes_comprimidos, codec_realmente_usado).

        AUTO nunca é o codec retornado — sempre resolve para um codec concreto,
        garantindo que o valor persistido em metadados seja decodificável.
        """
        if self is CompressionCodec.AUTO:
            return self._auto_compress(data, level)

        if self is CompressionCodec.GZIP:
            return gzip.compress(data, compresslevel=level), self
        if self is CompressionCodec.ZLIB:
            return zlib.compress(data, level=level), self
        if self is CompressionCodec.BZ2:
            import bz2
            return bz2.compress(data, compresslevel=min(9, max(1, level))), self
        if self is CompressionCodec.LZMA:
            return lzma.compress(data, preset=min(9, level)), self
        if self is CompressionCodec.ZSTANDARD:
            cctx = zstd.ZstdCompressor(level=level)
            return cctx.compress(data), self

        raise ValueError(f"Codec não suportado para compressão: {self}")

    def decompress(self, data: bytes) -> bytes:
        """Descomprime `data`. AUTO não é um codec válido para decompressão —
        o codec concreto usado deve estar persistido nos metadados."""
        if self is CompressionCodec.GZIP:
            return gzip.decompress(data)
        if self is CompressionCodec.ZLIB:
            return zlib.decompress(data)
        if self is CompressionCodec.BZ2:
            import bz2
            return bz2.decompress(data)
        if self is CompressionCodec.LZMA:
            return lzma.decompress(data)
        if self is CompressionCodec.ZSTANDARD:
            dctx = zstd.ZstdDecompressor()
            return dctx.decompress(data)

        raise ValueError(f"Decompressão não suportada para codec: {self}")

    def _auto_compress(self, data: bytes, level: int) -> Tuple[bytes, "CompressionCodec"]:
        """Seleciona automaticamente o melhor codec concreto para os dados.

        Para dados pequenos usa GZIP diretamente (overhead de outros codecs
        não compensa). Para dados maiores, testa candidatos numa amostra e
        comprime os dados completos apenas uma vez com o melhor candidato
        (evita compressão dupla quando a amostra == dados completos).
        """
        candidates = (
            CompressionCodec.ZSTANDARD,
            CompressionCodec.LZMA,
            CompressionCodec.GZIP,
        )

        if len(data) < 1024:
            compressed, _ = CompressionCodec.GZIP.compress(data, level)
            return compressed, CompressionCodec.GZIP

        sample = data[:4096]
        sample_is_full_data = len(sample) == len(data)

        best_codec = CompressionCodec.GZIP
        best_ratio = float("inf")
        best_sample_compressed: Optional[bytes] = None

        for codec in candidates:
            try:
                sample_compressed, _ = codec.compress(sample, level)
            except Exception:
                continue
            ratio = len(sample_compressed) / max(1, len(sample))
            if ratio < best_ratio:
                best_ratio = ratio
                best_codec = codec
                best_sample_compressed = sample_compressed

        if sample_is_full_data and best_sample_compressed is not None:
            return best_sample_compressed, best_codec

        compressed, _ = best_codec.compress(data, level)
        return compressed, best_codec


class ChecksumAlgorithm(Enum):
    """Algoritmos de checksum suportados."""
    SHA256 = "sha256"
    SHA512 = "sha512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"
    XXHASH = "xxhash"
    MD5 = "md5"

    def compute(self, data: bytes) -> str:
        if self is ChecksumAlgorithm.SHA256:
            return hashlib.sha256(data).hexdigest()
        if self is ChecksumAlgorithm.SHA512:
            return hashlib.sha512(data).hexdigest()
        if self is ChecksumAlgorithm.BLAKE2B:
            return hashlib.blake2b(data).hexdigest()
        if self is ChecksumAlgorithm.BLAKE2S:
            return hashlib.blake2s(data).hexdigest()
        if self is ChecksumAlgorithm.XXHASH:
            return xxhash.xxh64(data).hexdigest()
        if self is ChecksumAlgorithm.MD5:
            return hashlib.md5(data).hexdigest()
        raise ValueError(f"Algoritmo de checksum desconhecido: {self}")


class StorageBackend(Enum):
    """Backends de armazenamento."""
    LOCAL = "local"
    MEMORY = "memory"
    SHARDED_LOCAL = "sharded_local"
    REDIS = "redis"
    SQLITE = "sqlite"
    HYBRID = "hybrid"


class ConsistencyLevel(IntEnum):
    """Níveis de consistência."""
    EVENTUAL = 0
    STRONG = 1
    SEQUENTIAL = 2
    LINEARIZABLE = 3


class JournalOperation(str, Enum):
    """Operações registradas no journal."""
    SAVE = "save"
    LOAD = "load"
    DELETE = "delete"
    UPDATE = "update"
    ARCHIVE = "archive"
    RESTORE = "restore"
    VERIFY = "verify"
    COMPRESS = "compress"
    SHARD = "shard"
    MERGE = "merge"


# ─── Estruturas de Dados ────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ShardInfo:
    """Informações de um shard."""
    id: ShardId
    path: Path
    size_bytes: int
    checksum: Checksum
    created_at: datetime.datetime


@dataclass(slots=True)
class JournalEntry:
    """Entrada do journal para recovery."""
    id: JournalEntryId
    operation: JournalOperation
    version: VersionId
    timestamp: datetime.datetime
    data: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    retry_count: int = 0


@dataclass(slots=True, frozen=True)
class CacheEntry:
    """Entrada do cache com metadados."""
    data: Any
    created_at: float
    ttl: float
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    size_bytes: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class LRUCache(Generic[T]):
    """Cache LRU thread-safe com TTL e limite de memória aproximado."""

    def __init__(self, max_size: int = 1000, max_memory_mb: int = 1024):
        self._cache: OrderedDictType[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._current_memory = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> Optional[T]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.misses += 1
                cache_misses.inc()
                return None

            if entry.is_expired:
                self._remove(key)
                self.misses += 1
                cache_misses.inc()
                return None

            self._cache.move_to_end(key)
            updated = replace(entry, access_count=entry.access_count + 1, last_accessed=time.time())
            self._cache[key] = updated
            self.hits += 1
            cache_hits.inc()
            return updated.data

    def put(self, key: str, value: T, ttl: float = DEFAULT_CACHE_TTL):
        with self._lock:
            size_bytes = sys.getsizeof(value)

            if key in self._cache:
                self._current_memory -= self._cache[key].size_bytes
                del self._cache[key]

            while (len(self._cache) >= self.max_size or
                   self._current_memory + size_bytes > self.max_memory_bytes):
                if not self._evict_one():
                    break

            entry = CacheEntry(
                data=value,
                created_at=time.time(),
                ttl=ttl,
                size_bytes=size_bytes,
            )
            self._cache[key] = entry
            self._current_memory += size_bytes

    def _evict_one(self) -> bool:
        if not self._cache:
            return False
        key, _ = next(iter(self._cache.items()))
        self._remove(key)
        self.evictions += 1
        return True

    def _remove(self, key: str):
        entry = self._cache.pop(key, None)
        if entry:
            self._current_memory -= entry.size_bytes

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._current_memory = 0

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def memory_usage_mb(self) -> float:
        return self._current_memory / (1024 * 1024)


# ─── Database Layer ──────────────────────────────────────────────────────────
class VaultDatabase:
    """Camada de persistência SQLite com otimizações.

    NÃO é mais um singleton global: cada `AtenaMemoryVault` cria sua
    própria instância apontando para seu `base_dir`. Isso garante que
    múltiplas instâncias (ex: em testes com `tempfile.TemporaryDirectory`)
    não compartilhem estado acidentalmente.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._setup_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA mmap_size=268435456")
            self._local.connection = conn
        return conn

    def close(self):
        conn = getattr(self._local, 'connection', None)
        if conn is not None:
            conn.close()
            self._local.connection = None

    def _setup_database(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    current_version TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    metadata JSONB NOT NULL,
                    storage_path TEXT NOT NULL,
                    shard_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_archived BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (model_id) REFERENCES models(model_id)
                );

                CREATE INDEX IF NOT EXISTS idx_versions_model_id
                    ON versions(model_id);
                CREATE INDEX IF NOT EXISTS idx_versions_created_at
                    ON versions(created_at);
                CREATE INDEX IF NOT EXISTS idx_versions_archived
                    ON versions(is_archived);

                CREATE TABLE IF NOT EXISTS shards (
                    shard_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id TEXT NOT NULL,
                    shard_index INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    codec TEXT NOT NULL,
                    FOREIGN KEY (version_id) REFERENCES versions(version_id)
                );

                CREATE TABLE IF NOT EXISTS journal (
                    id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    version_id TEXT,
                    data BLOB,
                    metadata JSONB,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tags (
                    version_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (version_id, tag),
                    FOREIGN KEY (version_id) REFERENCES versions(version_id)
                );

                CREATE TABLE IF NOT EXISTS lineage (
                    version_id TEXT NOT NULL,
                    parent_version_id TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (version_id, parent_version_id),
                    FOREIGN KEY (version_id) REFERENCES versions(version_id),
                    FOREIGN KEY (parent_version_id) REFERENCES versions(version_id)
                );
            """)


# ─── Journal Manager ────────────────────────────────────────────────────────
class JournalManager:
    """Gerencia o journal append-only para recovery e auditoria.

    Suporta rotação por tempo: um novo arquivo é criado automaticamente
    quando o arquivo atual atinge `rotate_after_seconds` de idade.
    """

    def __init__(self, journal_path: Path,
                 rotate_after_seconds: int = DEFAULT_JOURNAL_ROTATE_SECONDS):
        self.journal_path = journal_path
        self.journal_path.mkdir(parents=True, exist_ok=True)
        self.rotate_after_seconds = rotate_after_seconds
        self._lock = threading.RLock()
        self._current_file: Optional[io.TextIOWrapper] = None
        self._current_file_opened_at: float = 0.0
        self._open_new_journal()

    def _open_new_journal(self):
        if self._current_file:
            self._current_file.close()

        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        journal_file = self.journal_path / f"journal_{timestamp}.log"
        self._current_file = open(journal_file, 'a', buffering=1)
        self._current_file_opened_at = time.monotonic()

    def _maybe_rotate(self):
        if time.monotonic() - self._current_file_opened_at >= self.rotate_after_seconds:
            self._open_new_journal()

    def append(self, entry: JournalEntry):
        """Adiciona uma entrada ao journal, rotacionando se necessário."""
        with self._lock:
            self._maybe_rotate()
            record = orjson.dumps({
                "id": entry.id,
                "operation": entry.operation.value,
                "version": entry.version,
                "timestamp": entry.timestamp.isoformat(),
                "status": entry.status,
                "metadata": _convert_sets(entry.metadata),
            }).decode()
            assert self._current_file is not None
            self._current_file.write(f"{record}\n")
            self._current_file.flush()

    def replay(self, since: Optional[datetime.datetime] = None) -> Iterator[JournalEntry]:
        """Itera entradas do journal (mais antigas primeiro) para recovery."""
        journal_files = sorted(self.journal_path.glob("journal_*.log"))

        for journal_file in journal_files:
            with open(journal_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = orjson.loads(line)
                        entry_time = datetime.datetime.fromisoformat(data['timestamp'])
                        if since and entry_time < since:
                            continue
                        yield JournalEntry(
                            id=JournalEntryId(data['id']),
                            operation=JournalOperation(data['operation']),
                            version=VersionId(data['version']),
                            timestamp=entry_time,
                            status=data['status'],
                            metadata=data.get('metadata', {}),
                        )
                    except Exception as e:
                        logger.error("journal_parse_error", error=str(e), line=line)

    def close(self):
        with self._lock:
            if self._current_file:
                self._current_file.close()
                self._current_file = None


# ─── Compression Engine ─────────────────────────────────────────────────────
class CompressionEngine:
    """Engine de compressão adaptativa com múltiplos codecs."""

    def __init__(self, default_codec: CompressionCodec = CompressionCodec.ZSTANDARD,
                 default_level: int = DEFAULT_COMPRESSION_LEVEL):
        self.default_codec = default_codec
        self.default_level = default_level
        self._stats: DefaultDict[str, Dict[str, float]] = defaultdict(lambda: {
            "compression_time": 0.0,
            "decompression_time": 0.0,
            "total_original_bytes": 0,
            "total_compressed_bytes": 0,
            "count": 0,
        })
        self._stats_lock = threading.Lock()

    def compress(self, data: bytes,
                  codec: Optional[CompressionCodec] = None,
                  level: Optional[int] = None) -> Tuple[bytes, CompressionCodec, int]:
        """Comprime `data`. Retorna (comprimido, codec_concreto_usado, level).

        Se `codec` for AUTO (ou None com `default_codec`=AUTO), o codec
        retornado é sempre concreto e decodificável — nunca AUTO.
        """
        codec = codec or self.default_codec
        level = level if level is not None else self.default_level

        start_time = time.perf_counter()
        compressed, codec_used = codec.compress(data, level)
        elapsed = time.perf_counter() - start_time

        with self._stats_lock:
            stats = self._stats[codec_used.value]
            stats["compression_time"] += elapsed
            stats["total_original_bytes"] += len(data)
            stats["total_compressed_bytes"] += len(compressed)
            stats["count"] += 1

        ratio = len(compressed) / len(data) if data else 0.0
        compression_ratio_metric.observe(ratio)

        return compressed, codec_used, level

    def decompress(self, data: bytes, codec: CompressionCodec) -> bytes:
        """Descomprime `data` usando um codec concreto (não AUTO)."""
        if codec is CompressionCodec.AUTO:
            raise ValueError(
                "AUTO não é um codec válido para decompressão; "
                "o codec concreto usado deve ter sido persistido nos metadados."
            )

        start_time = time.perf_counter()
        decompressed = codec.decompress(data)
        elapsed = time.perf_counter() - start_time

        with self._stats_lock:
            self._stats[codec.value]["decompression_time"] += elapsed

        return decompressed

    @property
    def statistics(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {k: dict(v) for k, v in self._stats.items()}


# ─── Shard Manager ──────────────────────────────────────────────────────────
class ShardManager:
    """Gerencia sharding de modelos grandes."""

    def __init__(self, shard_size_mb: int, base_dir: Path):
        self.shard_size = shard_size_mb * 1024 * 1024
        self.base_dir = base_dir / "shards"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def shard_data(self, data: bytes, version_id: VersionId) -> List[ShardInfo]:
        """Divide `data` em shards e os grava em disco (operação síncrona,
        deve ser chamada via `asyncio.to_thread` em contexto assíncrono)."""
        shards: List[ShardInfo] = []
        total_size = len(data)
        num_shards = max(1, (total_size + self.shard_size - 1) // self.shard_size)

        version_dir = self.base_dir / version_id
        version_dir.mkdir(parents=True, exist_ok=True)

        for i in range(num_shards):
            start = i * self.shard_size
            end = min(start + self.shard_size, total_size)
            chunk = data[start:end]

            shard_path = version_dir / f"shard_{i:04d}.bin"
            with open(shard_path, 'wb') as f:
                f.write(chunk)

            checksum = ChecksumAlgorithm.BLAKE2B.compute(chunk)

            shards.append(ShardInfo(
                id=ShardId(i),
                path=shard_path,
                size_bytes=len(chunk),
                checksum=Checksum(checksum),
                created_at=datetime.datetime.utcnow(),
            ))

        return shards

    def reconstruct_data(self, shards: List[ShardInfo]) -> bytes:
        """Reconstrói os dados originais a partir dos shards, verificando
        a integridade de cada um via checksum."""
        sorted_shards = sorted(shards, key=lambda s: s.id)

        parts: List[bytes] = []
        for shard in sorted_shards:
            if not shard.path.exists():
                raise FileNotFoundError(f"Shard não encontrado: {shard.path}")

            with open(shard.path, 'rb') as f:
                chunk = f.read()

            computed = ChecksumAlgorithm.BLAKE2B.compute(chunk)
            if computed != shard.checksum:
                raise ValueError(f"Checksum inválido para shard {shard.id}")

            parts.append(chunk)

        return b''.join(parts)

    def cleanup_shards(self, version_id: VersionId):
        version_dir = self.base_dir / version_id
        if version_dir.exists():
            shutil.rmtree(version_dir)


# ─── Event System ───────────────────────────────────────────────────────────
class EventType(str, Enum):
    MODEL_SAVED = "model.saved"
    MODEL_LOADED = "model.loaded"
    MODEL_DELETED = "model.deleted"
    MODEL_ARCHIVED = "model.archived"
    VERSION_CREATED = "version.created"
    SHARD_CREATED = "shard.created"
    COMPRESSION_COMPLETED = "compression.completed"
    ERROR_OCCURRED = "error.occurred"
    CLEANUP_COMPLETED = "cleanup.completed"


@dataclass(slots=True)
class VaultEvent:
    type: EventType
    version: Optional[VersionId] = None
    model_id: Optional[ModelId] = None
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Bus de eventos pub/sub simples, com executor compartilhado para
    callbacks síncronos (não bloqueia o event loop por publish)."""

    def __init__(self, max_workers: int = 4):
        self._subscribers: DefaultDict[EventType, List[Callable]] = defaultdict(list)
        self._async_subscribers: DefaultDict[EventType, List[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vault-events")

    def subscribe(self, event_type: EventType, callback: Callable):
        with self._lock:
            self._subscribers[event_type].append(callback)

    def subscribe_async(self, event_type: EventType, callback: Callable):
        with self._lock:
            self._async_subscribers[event_type].append(callback)

    async def publish(self, event: VaultEvent):
        loop = asyncio.get_running_loop()

        sync_callbacks = list(self._subscribers.get(event.type, []))
        futures = [
            loop.run_in_executor(self._executor, callback, event)
            for callback in sync_callbacks
        ]

        async_callbacks = list(self._async_subscribers.get(event.type, []))
        tasks = [asyncio.create_task(callback(event)) for callback in async_callbacks]

        all_awaitables = futures + tasks
        if all_awaitables:
            await asyncio.gather(*all_awaitables, return_exceptions=True)

    def shutdown(self):
        self._executor.shutdown(wait=True)


# ─── ATENA Memory Vault Principal ───────────────────────────────────────────
class AtenaMemoryVault:
    """
    ATENA Memory Vault v3.1 - Sistema de versionamento de modelos de IA
    com compressão adaptativa, sharding, journaling e alta disponibilidade.

    Cada instância é independente (não há mais singleton global), de modo
    que múltiplos vaults com `base_dir` diferentes podem coexistir — por
    exemplo, em testes paralelos. Para um vault compartilhado por toda a
    aplicação, use `AtenaMemoryVault.get_default()`.
    """

    _default_instance: ClassVar[Optional['AtenaMemoryVault']] = None
    _default_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self,
                 base_dir: Optional[Path] = None,
                 max_versions: int = DEFAULT_MAX_VERSIONS,
                 cache_ttl: float = DEFAULT_CACHE_TTL,
                 compression_codec: CompressionCodec = CompressionCodec.AUTO,
                 compression_level: int = DEFAULT_COMPRESSION_LEVEL,
                 storage_backend: StorageBackend = StorageBackend.HYBRID,
                 enable_sharding: bool = True,
                 enable_journaling: bool = True,
                 enable_cache: bool = True,
                 enable_auto_cleanup: bool = True,
                 consistency_level: ConsistencyLevel = ConsistencyLevel.STRONG,
                 redis_url: Optional[str] = None,
                 shard_size_mb: int = DEFAULT_SHARD_SIZE_MB,
                 journal_rotate_seconds: int = DEFAULT_JOURNAL_ROTATE_SECONDS):

        self.base_dir = Path(base_dir or BASE_DIR)
        self.max_versions = max_versions
        self.cache_ttl = cache_ttl
        self.compression_codec = compression_codec
        self.compression_level = compression_level
        self.storage_backend = storage_backend
        self.enable_sharding = enable_sharding
        self.enable_journaling = enable_journaling
        self.enable_cache = enable_cache
        self.enable_auto_cleanup = enable_auto_cleanup
        self.consistency_level = consistency_level

        # Componentes
        self._setup_directories()
        self.db = VaultDatabase(self.base_dir / DEFAULT_SQLITE_FILENAME)
        self.compression_engine = CompressionEngine(compression_codec, compression_level)
        self.shard_manager = ShardManager(shard_size_mb, self.base_dir)
        self.journal_manager: Optional[JournalManager] = (
            JournalManager(self.base_dir / "journal", journal_rotate_seconds)
            if enable_journaling else None
        )
        self.event_bus = EventBus()

        # Cache
        self._cache = LRUCache[Any](max_size=2000, max_memory_mb=2048)
        self._metadata_cache = LRUCache[ModelMetadata](max_size=5000)

        # Redis (opcional, lazy init)
        self._redis: Optional["aioredis.Redis"] = None
        self._redis_url: Optional[str] = None
        if storage_backend == StorageBackend.HYBRID and aioredis is not None:
            self._redis_url = redis_url or DEFAULT_REDIS_URL

        # Locks
        self._save_lock = asyncio.Lock()
        self._cleanup_lock = asyncio.Lock()

        self._closed = False

        logger.info("vault_initialized",
                    base_dir=str(self.base_dir),
                    max_versions=max_versions,
                    compression_codec=compression_codec.value)

    # ── Instância padrão compartilhada (opt-in) ────────────────────────────
    @classmethod
    def get_default(cls, **kwargs) -> "AtenaMemoryVault":
        """Retorna (criando se necessário) uma instância padrão compartilhada,
        útil para uso simples em scripts. Testes que precisam de isolamento
        devem instanciar a classe diretamente com um `base_dir` próprio."""
        with cls._default_lock:
            if cls._default_instance is None:
                cls._default_instance = cls(**kwargs)
            return cls._default_instance

    # ── Setup ───────────────────────────────────────────────────────────────
    def _setup_directories(self):
        dirs = [
            self.base_dir,
            self.base_dir / "models",
            self.base_dir / "backups",
            self.base_dir / "shards",
            self.base_dir / "temp",
            self.base_dir / "journal",
            self.base_dir / "logs",
            self.base_dir / "checkpoints",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            (d / ".gitkeep").touch(exist_ok=True)

    @contextmanager
    def _measure_latency(self, operation: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            operation_latency.labels(operation=operation).observe(elapsed)

    async def _ensure_redis(self):
        if self._redis is None and self._redis_url and aioredis is not None:
            self._redis = await aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=False,
                max_connections=20,
            )

    # ── Save ────────────────────────────────────────────────────────────────
    async def save_model_async(self,
                                model_data: Dict[str, Any],
                                weights_data: bytes,
                                loss: float,
                                accuracy: float,
                                model_id: Optional[str] = None,
                                validation_data: Optional[Tuple[float, float]] = None,
                                tags: Optional[Set[str]] = None,
                                training_config: Optional[Dict[str, Any]] = None,
                                custom_metadata: Optional[Dict[str, Any]] = None,
                                parent_version: Optional[VersionId] = None) -> VersionId:
        """
        Salva um modelo de forma assíncrona com compressão adaptativa,
        sharding (se necessário), checksums múltiplos e journaling.

        Args:
            model_data: Dicionário com a arquitetura/configuração do modelo.
            weights_data: Bytes dos pesos do modelo.
            loss: Valor de loss do treinamento (>= 0).
            accuracy: Acurácia do modelo (0-1).
            model_id: ID do modelo (gerado automaticamente se None).
            validation_data: Tupla (val_loss, val_accuracy).
            tags: Conjunto de tags para categorização.
            training_config: Configuração de treinamento.
            custom_metadata: Metadados adicionais definidos pelo usuário.
            parent_version: Versão pai, para rastreamento de linhagem.

        Returns:
            VersionId da versão criada.

        Raises:
            ValueError: Se loss/accuracy forem inválidos.
            RuntimeError: Se a persistência falhar (com rollback do disco).
        """
        with self._measure_latency("save"):
            if loss < 0:
                raise ValueError(f"Loss deve ser >= 0, recebido: {loss}")
            if not 0 <= accuracy <= 1:
                raise ValueError(f"Accuracy deve estar entre 0 e 1, recebido: {accuracy}")

            model_id = ModelId(model_id or str(uuid.uuid4()))
            version_id = VersionId(
                f"v{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{secrets.token_hex(4)}"
            )

            # Compressão adaptativa: codec_used é sempre concreto (nunca AUTO).
            compressed_data, codec_used, _level_used = self.compression_engine.compress(
                weights_data, self.compression_codec, self.compression_level
            )

            checksums = {
                "sha256": ChecksumAlgorithm.SHA256.compute(weights_data),
                "blake2b": ChecksumAlgorithm.BLAKE2B.compute(weights_data),
                "xxhash": ChecksumAlgorithm.XXHASH.compute(weights_data),
            }

            # Sharding (em thread separada para não bloquear o event loop)
            shards: Optional[List[ShardInfo]] = None
            if self.enable_sharding and len(compressed_data) > self.shard_manager.shard_size:
                shards = await asyncio.to_thread(
                    self.shard_manager.shard_data, compressed_data, version_id
                )

            merged_custom_metadata = {
                **(custom_metadata or {}),
                "codec": codec_used.value,
            }

            metadata = ModelMetadata(
                version=version_id,
                model_id=model_id,
                timestamp=datetime.datetime.now(),
                loss=loss,
                accuracy=accuracy,
                validation_loss=validation_data[0] if validation_data else None,
                validation_accuracy=validation_data[1] if validation_data else None,
                model_size_bytes=len(weights_data),
                compressed_size_bytes=len(compressed_data),
                checksum_sha256=Checksum(checksums["sha256"]),
                checksum_blake2b=Checksum(checksums["blake2b"]),
                checksum_xxhash=Checksum(checksums["xxhash"]),
                parent_version=parent_version,
                tags=tags or set(),
                training_config=TrainingConfig(**(training_config or {})),
                custom_metadata=merged_custom_metadata,
                is_verified=True,
            )

            model_path = self.base_dir / "models" / version_id

            async with self._save_lock:
                try:
                    model_path.mkdir(parents=True, exist_ok=False)

                    if shards:
                        # Os shards já foram gravados em disco por shard_data();
                        # apenas registramos os metadados deles no banco.
                        pass
                    else:
                        weights_path = model_path / "weights.bin"
                        async with aiofiles.open(weights_path, 'wb') as f:
                            await f.write(compressed_data)

                    async with aiofiles.open(model_path / "model.json", 'w') as f:
                        await f.write(orjson.dumps(_convert_sets(model_data)).decode())

                    async with aiofiles.open(model_path / "metadata.json", 'wb') as f:
                        await f.write(orjson.dumps(metadata.to_jsonable()))

                    conn = self.db._get_connection()
                    with conn:
                        conn.execute(
                            """INSERT OR REPLACE INTO models (model_id, current_version, updated_at)
                               VALUES (?, ?, CURRENT_TIMESTAMP)""",
                            (model_id, version_id),
                        )
                        conn.execute(
                            """INSERT INTO versions (version_id, model_id, metadata, storage_path, shard_count)
                               VALUES (?, ?, ?, ?, ?)""",
                            (version_id, model_id, orjson.dumps(metadata.to_jsonable()).decode(),
                             str(model_path), len(shards) if shards else 1),
                        )

                        if shards:
                            conn.executemany(
                                """INSERT INTO shards
                                   (version_id, shard_index, file_path, size_bytes, checksum, codec)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                [
                                    (version_id, shard.id, str(shard.path), shard.size_bytes,
                                     shard.checksum, codec_used.value)
                                    for shard in shards
                                ],
                            )

                        if parent_version:
                            conn.execute(
                                "INSERT OR IGNORE INTO lineage (version_id, parent_version_id) VALUES (?, ?)",
                                (version_id, parent_version),
                            )

                        if tags:
                            conn.executemany(
                                "INSERT INTO tags (version_id, tag) VALUES (?, ?)",
                                [(version_id, tag) for tag in tags],
                            )

                    if self.enable_journaling and self.journal_manager:
                        entry = JournalEntry(
                            id=JournalEntryId(str(uuid.uuid4())),
                            operation=JournalOperation.SAVE,
                            version=version_id,
                            timestamp=datetime.datetime.utcnow(),
                            status="completed",
                        )
                        self.journal_manager.append(entry)

                    if self.enable_cache:
                        cache_data = (model_data, weights_data, metadata)
                        self._cache.put(str(version_id), cache_data, self.cache_ttl)
                        self._metadata_cache.put(f"metadata:{version_id}", metadata, self.cache_ttl * 2)

                    await self.event_bus.publish(VaultEvent(
                        type=EventType.MODEL_SAVED,
                        version=version_id,
                        model_id=model_id,
                        metadata={"accuracy": accuracy, "loss": loss},
                    ))

                    model_saves.labels(status="success").inc()
                    model_versions.inc()
                    storage_bytes.inc(len(compressed_data))

                    logger.info("model_saved",
                                 version_id=version_id,
                                 model_id=model_id,
                                 accuracy=accuracy,
                                 loss=loss,
                                 codec=codec_used.value,
                                 compressed_size=len(compressed_data),
                                 sharded=bool(shards))

                    if self.enable_auto_cleanup:
                        asyncio.create_task(self._cleanup_old_versions_async())

                    return version_id

                except Exception as e:
                    if model_path.exists():
                        shutil.rmtree(model_path, ignore_errors=True)
                    if shards:
                        self.shard_manager.cleanup_shards(version_id)

                    model_saves.labels(status="error").inc()
                    logger.error("model_save_failed", version_id=version_id, error=str(e))
                    raise RuntimeError(f"Falha ao salvar modelo: {e}") from e

    def save_model(self, *args, **kwargs) -> VersionId:
        """Wrapper síncrono para save_model_async (use apenas fora de loops async)."""
        return asyncio.run(self.save_model_async(*args, **kwargs))

    # ── Load ────────────────────────────────────────────────────────────────
    async def load_model_async(self,
                                version: Optional[VersionId] = None,
                                model_id: Optional[ModelId] = None,
                                use_cache: bool = True) -> Optional[Tuple[Dict[str, Any], bytes, ModelMetadata]]:
        """
        Carrega um modelo de forma assíncrona, com cache local e Redis opcional.

        Args:
            version: VersionId específico (None = resolvido a partir de model_id ou melhor versão).
            model_id: ModelId para buscar a versão atual.
            use_cache: Se deve consultar/atualizar caches.

        Returns:
            Tupla (model_data, weights_data, metadata) ou None se não encontrado.
        """
        with self._measure_latency("load"):
            if version is None and model_id:
                version = await self._get_current_version_async(model_id)
            elif version is None:
                version = await self._get_best_version_async()

            if version is None:
                model_loads.labels(status="not_found").inc()
                return None

            cache_key = f"model:{version}"

            if use_cache and self.enable_cache:
                cached = self._cache.get(cache_key)
                if cached:
                    model_loads.labels(status="cache_hit").inc()
                    logger.debug("cache_hit", version=version)
                    return cached

            if use_cache and self.storage_backend == StorageBackend.HYBRID:
                await self._ensure_redis()

            if self._redis and use_cache:
                try:
                    redis_key = f"atena:model:{version}"
                    cached_bytes = await self._redis.get(redis_key)
                    if cached_bytes:
                        model_loads.labels(status="redis_hit").inc()
                        result = pickle.loads(cached_bytes)
                        if self.enable_cache:
                            self._cache.put(cache_key, result, self.cache_ttl)
                        return result
                except Exception as e:
                    logger.warning("redis_cache_error", error=str(e))

            model_path = self.base_dir / "models" / version

            if not model_path.exists():
                model_loads.labels(status="not_found").inc()
                logger.warning("model_not_found", version=version)
                return None

            try:
                async with aiofiles.open(model_path / "metadata.json", 'rb') as f:
                    metadata_bytes = await f.read()
                metadata = ModelMetadata(**orjson.loads(metadata_bytes))

                async with aiofiles.open(model_path / "model.json", 'r') as f:
                    model_json = await f.read()
                model_data = orjson.loads(model_json)

                weights_path = model_path / "weights.bin"
                if weights_path.exists():
                    async with aiofiles.open(weights_path, 'rb') as f:
                        compressed_weights = await f.read()
                else:
                    shards = await asyncio.to_thread(self._get_shards_for_version, version)
                    if not shards:
                        raise FileNotFoundError(f"Pesos não encontrados para a versão {version}")
                    compressed_weights = await asyncio.to_thread(
                        self.shard_manager.reconstruct_data, shards
                    )

                codec_name = metadata.custom_metadata.get("codec", "zstandard")
                try:
                    codec = CompressionCodec(codec_name)
                except ValueError:
                    logger.warning("unknown_codec_fallback", version=version, codec=codec_name)
                    codec = CompressionCodec.ZSTANDARD

                weights_data = self.compression_engine.decompress(compressed_weights, codec)

                computed = ChecksumAlgorithm.BLAKE2B.compute(weights_data)
                if metadata.checksum_blake2b and computed != metadata.checksum_blake2b:
                    raise ValueError(f"Checksum inválido para versão {version}")

                result = (model_data, weights_data, metadata)

                if self.enable_cache:
                    self._cache.put(cache_key, result, self.cache_ttl)
                    self._metadata_cache.put(f"metadata:{version}", metadata, self.cache_ttl * 2)

                if self._redis:
                    try:
                        redis_key = f"atena:model:{version}"
                        await self._redis.setex(
                            redis_key,
                            int(self.cache_ttl),
                            pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL),
                        )
                    except Exception as e:
                        logger.warning("redis_cache_write_error", error=str(e))

                model_loads.labels(status="success").inc()
                logger.info("model_loaded", version=version, accuracy=metadata.accuracy)

                return result

            except Exception as e:
                model_loads.labels(status="error").inc()
                logger.error("model_load_failed", version=version, error=str(e))
                return None

    def load_model(self, *args, **kwargs):
        """Wrapper síncrono para load_model_async (use apenas fora de loops async)."""
        return asyncio.run(self.load_model_async(*args, **kwargs))

    # ── Consultas auxiliares ───────────────────────────────────────────────
    async def _get_best_version_async(self, metric: str = 'accuracy') -> Optional[VersionId]:
        """Retorna a melhor versão não arquivada segundo `metric`.

        `metric` é validada contra uma allowlist para evitar injeção SQL.
        """
        if metric not in ALLOWED_RANKING_METRICS:
            raise ValueError(
                f"Métrica '{metric}' não suportada. Use uma de: {sorted(ALLOWED_RANKING_METRICS)}"
            )

        # 'loss' e '*_loss' são melhores quando menores; demais, maiores é melhor.
        direction = "ASC" if metric.endswith("loss") else "DESC"
        json_path = f"$.{metric}"

        conn = self.db._get_connection()
        row = conn.execute(
            f"""
            SELECT version_id FROM versions
            WHERE is_archived = FALSE
              AND json_extract(metadata, ?) IS NOT NULL
            ORDER BY json_extract(metadata, ?) {direction}
            LIMIT 1
            """,
            (json_path, json_path),
        ).fetchone()

        return VersionId(row[0]) if row else None

    async def _get_current_version_async(self, model_id: ModelId) -> Optional[VersionId]:
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT current_version FROM models WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        return VersionId(row[0]) if row else None

    def _get_shards_for_version(self, version_id: VersionId) -> List[ShardInfo]:
        conn = self.db._get_connection()
        rows = conn.execute(
            """SELECT shard_id, shard_index, file_path, size_bytes, checksum
               FROM shards WHERE version_id = ? ORDER BY shard_index""",
            (version_id,),
        ).fetchall()

        return [
            ShardInfo(
                id=ShardId(row['shard_index']),
                path=Path(row['file_path']),
                size_bytes=row['size_bytes'],
                checksum=Checksum(row['checksum']),
                created_at=datetime.datetime.utcnow(),
            )
            for row in rows
        ]

    async def _list_versions_async(self, filters: Optional[Dict] = None) -> List[VersionId]:
        conn = self.db._get_connection()
        query = "SELECT version_id FROM versions WHERE 1=1"
        params: List[Any] = []

        if filters:
            if 'model_id' in filters:
                query += " AND model_id = ?"
                params.append(filters['model_id'])
            if 'archived' in filters:
                query += " AND is_archived = ?"
                params.append(bool(filters['archived']))

        rows = conn.execute(query, params).fetchall()
        return [VersionId(row[0]) for row in rows]

    # ── Cleanup / Archive ──────────────────────────────────────────────────
    async def _cleanup_old_versions_async(self):
        """Arquiva versões excedentes, mantendo as `max_versions` melhores
        (por accuracy desc, loss asc)."""
        async with self._cleanup_lock:
            conn = self.db._get_connection()

            count_row = conn.execute(
                "SELECT COUNT(*) FROM versions WHERE is_archived = FALSE"
            ).fetchone()

            if count_row[0] <= self.max_versions:
                return

            to_archive = conn.execute("""
                SELECT version_id FROM versions
                WHERE is_archived = FALSE
                ORDER BY json_extract(metadata, '$.accuracy') DESC,
                         json_extract(metadata, '$.loss') ASC
                LIMIT -1 OFFSET ?
            """, (self.max_versions,)).fetchall()

            archived_count = 0
            for row in to_archive:
                version_id = VersionId(row[0])
                try:
                    await self._archive_version_async(version_id)
                    archived_count += 1
                except Exception as e:
                    logger.error("archive_failed", version=version_id, error=str(e))

            logger.info("cleanup_completed", archived=archived_count, remaining=self.max_versions)

            await self.event_bus.publish(VaultEvent(
                type=EventType.CLEANUP_COMPLETED,
                metadata={"archived_count": archived_count},
            ))

    async def _archive_version_async(self, version_id: VersionId):
        model_path = self.base_dir / "models" / version_id
        archive_path = self.base_dir / "backups" / f"archive_{version_id}_{int(time.time())}"

        if model_path.exists():
            await asyncio.to_thread(shutil.copytree, model_path, archive_path)
            await asyncio.to_thread(shutil.rmtree, model_path)

        conn = self.db._get_connection()
        with conn:
            conn.execute(
                "UPDATE versions SET is_archived = TRUE WHERE version_id = ?",
                (version_id,),
            )

        self._cache._remove(str(version_id))
        self._cache._remove(f"model:{version_id}")
        self._metadata_cache._remove(f"metadata:{version_id}")

        if self._redis:
            try:
                await self._redis.delete(f"atena:model:{version_id}")
            except Exception as e:
                logger.warning("redis_archive_cleanup_error", error=str(e))

        await self.event_bus.publish(VaultEvent(
            type=EventType.MODEL_ARCHIVED,
            version=version_id,
        ))

    # ── Health / Métricas ──────────────────────────────────────────────────
    async def perform_health_check(self) -> List[str]:
        """Executa uma verificação de saúde e retorna a lista de problemas
        encontrados (vazia se tudo estiver OK)."""
        issues: List[str] = []

        disk_usage = shutil.disk_usage(self.base_dir)
        if disk_usage.free < 100 * 1024 * 1024:
            issues.append(f"Espaço em disco baixo: {disk_usage.free / (1024 ** 3):.2f}GB")

        try:
            conn = self.db._get_connection()
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                issues.append(f"Banco de dados com problemas de integridade: {result[0]}")
        except Exception as e:
            issues.append(f"Banco de dados corrompido: {e}")

        max_memory_mb = self._cache.max_memory_bytes / 1024 / 1024
        if self._cache.memory_usage_mb > 0.9 * max_memory_mb:
            issues.append(f"Cache próximo do limite: {self._cache.memory_usage_mb:.0f}MB")

        if issues:
            logger.warning("health_check_issues", issues=issues)
        else:
            logger.info("health_check_ok")

        return issues

    async def update_prometheus_metrics(self):
        """Atualiza os gauges de Prometheus com o estado atual do vault."""
        model_versions.set(len(await self._list_versions_async()))

        total_size = await asyncio.to_thread(self._compute_total_weights_size)
        storage_bytes.set(total_size)

    def _compute_total_weights_size(self) -> int:
        models_dir = self.base_dir / "models"
        return sum(
            f.stat().st_size
            for f in models_dir.rglob("weights.bin")
            if f.exists()
        ) + sum(
            f.stat().st_size
            for f in (self.base_dir / "shards").rglob("shard_*.bin")
            if f.exists()
        )

    # ── Export / Import ─────────────────────────────────────────────────────
    async def export_model_async(self,
                                  version: VersionId,
                                  export_path: Path,
                                  include_shards: bool = True) -> bool:
        """Exporta um modelo (metadados + pesos) para um arquivo msgpack portável."""
        result = await self.load_model_async(version=version, use_cache=False)
        if not result:
            return False

        model_data, weights_data, metadata = result

        export_bundle = {
            "version": "3.1.0",
            "vault_version": version,
            "metadata": metadata.to_jsonable(),
            "model_data": model_data,
            "weights_data": weights_data,
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "checksums": {
                "sha256": ChecksumAlgorithm.SHA256.compute(weights_data),
                "blake2b": ChecksumAlgorithm.BLAKE2B.compute(weights_data),
            },
        }

        export_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(export_path, 'wb') as f:
            await f.write(msgpack.packb(export_bundle, use_bin_type=True))

        logger.info("model_exported", version=version, path=str(export_path))
        return True

    async def import_model_async(self, import_path: Path) -> Optional[VersionId]:
        """Importa um modelo de um arquivo exportado por `export_model_async`."""
        if not import_path.exists():
            logger.error("import_file_not_found", path=str(import_path))
            return None

        async with aiofiles.open(import_path, 'rb') as f:
            data = await f.read()

        bundle = msgpack.unpackb(data, raw=False)

        required = {'model_data', 'weights_data', 'metadata'}
        if not required.issubset(bundle.keys()):
            raise ValueError("Bundle de importação inválido: campos obrigatórios ausentes")

        metadata = ModelMetadata(**bundle['metadata'])

        version = await self.save_model_async(
            model_data=bundle['model_data'],
            weights_data=bundle['weights_data'],
            loss=metadata.loss,
            accuracy=metadata.accuracy,
            tags=metadata.tags | {'imported'},
            custom_metadata={
                **{k: v for k, v in metadata.custom_metadata.items() if k != "codec"},
                'imported_from': str(import_path),
                'imported_at': datetime.datetime.utcnow().isoformat(),
                'original_version': metadata.version,
            },
        )

        logger.info("model_imported", version=version, source=str(import_path))
        return version

    # ── Estatísticas ─────────────────────────────────────────────────────────
    def get_statistics(self) -> Dict[str, Any]:
        """Retorna estatísticas agregadas do vault."""
        conn = self.db._get_connection()

        stats = conn.execute("""
            SELECT
                COUNT(*) as total_versions,
                COUNT(DISTINCT model_id) as total_models,
                AVG(json_extract(metadata, '$.accuracy')) as avg_accuracy,
                MIN(json_extract(metadata, '$.loss')) as min_loss,
                MAX(json_extract(metadata, '$.accuracy')) as max_accuracy,
                SUM(json_extract(metadata, '$.model_size_bytes')) as total_size_bytes,
                SUM(json_extract(metadata, '$.compressed_size_bytes')) as total_compressed_bytes
            FROM versions
            WHERE is_archived = FALSE
        """).fetchone()

        total_size_bytes = stats['total_size_bytes'] or 0
        total_compressed_bytes = stats['total_compressed_bytes'] or 0
        total_hits = self._cache.hits
        total_misses = self._cache.misses

        return {
            "total_versions": stats['total_versions'],
            "total_models": stats['total_models'],
            "avg_accuracy": stats['avg_accuracy'] or 0,
            "best_loss": stats['min_loss'] or 0,
            "best_accuracy": stats['max_accuracy'] or 0,
            "total_storage_bytes": total_size_bytes,
            "total_compressed_bytes": total_compressed_bytes,
            "compression_ratio": (
                total_compressed_bytes / total_size_bytes if total_size_bytes else 0
            ),
            "cache_size": self._cache.size,
            "cache_memory_mb": self._cache.memory_usage_mb,
            "cache_hits": total_hits,
            "cache_misses": total_misses,
            "cache_hit_ratio": (
                total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0
            ),
            "compression_stats": self.compression_engine.statistics,
        }

    # ── Lifecycle ────────────────────────────────────────────────────────────
    async def aclose(self):
        """Libera recursos (conexões Redis, journal, executores)."""
        if self._closed:
            return
        self._closed = True

        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass

        if self.journal_manager:
            self.journal_manager.close()

        self.event_bus.shutdown()
        self.db.close()

    async def __aenter__(self) -> "AtenaMemoryVault":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()


# ─── FastAPI Application ────────────────────────────────────────────────────
def create_app(vault: AtenaMemoryVault) -> FastAPI:
    """Cria a aplicação FastAPI para expor o vault via API REST."""

    app = FastAPI(
        title="ATENA Memory Vault API",
        version="3.1.0",
        description="API RESTful para versionamento de modelos de IA",
    )

    @app.get("/health")
    async def health():
        issues = await vault.perform_health_check()
        return {
            "status": "healthy" if not issues else "degraded",
            "issues": issues,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    @app.get("/stats")
    async def get_statistics():
        return vault.get_statistics()

    @app.post("/models")
    async def save_model(
        model_data: Dict[str, Any],
        weights_b64: str,
        loss: float = Query(..., ge=0),
        accuracy: float = Query(..., ge=0, le=1),
        tags: Optional[List[str]] = Query(None),
    ):
        try:
            weights_data = base64.b64decode(weights_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="weights_b64 inválido")

        version = await vault.save_model_async(
            model_data=model_data,
            weights_data=weights_data,
            loss=loss,
            accuracy=accuracy,
            tags=set(tags) if tags else None,
        )

        return {"version": version}

    @app.get("/models/{version}")
    async def load_model(version: str):
        result = await vault.load_model_async(version=VersionId(version))
        if not result:
            raise HTTPException(status_code=404, detail="Modelo não encontrado")

        model_data, weights_data, metadata = result
        return {
            "version": version,
            "metadata": metadata.to_jsonable(),
            "model_data": model_data,
            "weights_b64": base64.b64encode(weights_data).decode(),
        }

    @app.get("/models/best")
    async def get_best_model(metric: str = "accuracy"):
        try:
            version = await vault._get_best_version_async(metric)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if not version:
            raise HTTPException(status_code=404, detail="Nenhum modelo encontrado")
        return {"best_version": version}

    return app


# ─── Testes ─────────────────────────────────────────────────────────────────
async def run_advanced_tests() -> int:
    """Suíte de testes de integração do vault."""
    import tempfile
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console()

    console.print("[bold cyan]\n╔══════════════════════════════════════════════════════════════╗\n"
                   "║     ATENA MEMORY VAULT v3.1 - TESTES AVANÇADOS                ║\n"
                   "╚══════════════════════════════════════════════════════════════╝[/]\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir) / "test_vault"

        async with AtenaMemoryVault(
            base_dir=vault_path,
            max_versions=10,
            cache_ttl=60,
            compression_codec=CompressionCodec.AUTO,
            shard_size_mb=1,  # shard pequeno para forçar sharding nos testes
            enable_sharding=True,
            enable_journaling=True,
            enable_auto_cleanup=False,  # cleanup controlado manualmente no teste
        ) as vault:

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:

                # Teste 1: salvar modelos (alguns grandes o suficiente para shard)
                task = progress.add_task("[green]Salvando modelos...", total=20)
                versions: List[VersionId] = []

                for i in range(20):
                    model_data = {
                        "name": f"model_{i}",
                        "layers": [
                            {"type": "Dense", "units": 64 * (i % 5 + 1)},
                            {"type": "Dropout", "rate": 0.2},
                            {"type": "Dense", "units": 10},
                        ],
                    }

                    # Dados incompressíveis grandes o suficiente para shard com shard_size_mb=1
                    weights_data = os.urandom(2 * 1024 * 1024)  # 2MB
                    loss = 0.5 / (i + 1)
                    accuracy = 0.7 + (i * 0.015)

                    version = await vault.save_model_async(
                        model_data, weights_data, loss, accuracy,
                        tags={f"test_{i}", "batch_test"},
                        training_config={"epochs": i + 1, "batch_size": 32},
                    )
                    versions.append(version)
                    progress.update(task, advance=1)

                # Teste 2: carregar e verificar integridade (inclui reconstrução de shards)
                task = progress.add_task("[blue]Verificando integridade...", total=10)

                for i in range(10):
                    version = versions[i]
                    result = await vault.load_model_async(version=version, use_cache=False)

                    assert result is not None, f"Falha ao carregar {version}"
                    _, weights, meta = result
                    assert len(weights) == 2 * 1024 * 1024, f"Tamanho incorreto para {version}"
                    assert abs(meta.accuracy - (0.7 + (i * 0.015))) < 1e-9

                    progress.update(task, advance=1)

                # Teste 3: cache
                task = progress.add_task("[yellow]Testando cache...", total=100)

                for _ in range(100):
                    await vault.load_model_async(version=versions[0])
                    progress.update(task, advance=1)

                stats = vault.get_statistics()
                assert stats['cache_hits'] > 0, "Cache não está funcionando"

                # Teste 4: export/import
                task = progress.add_task("[magenta]Testando export/import...", total=1)

                export_path = Path(tmpdir) / "exported_model.msgpack"
                success = await vault.export_model_async(versions[0], export_path)
                assert success, "Exportação falhou"

                imported = await vault.import_model_async(export_path)
                assert imported is not None, "Importação falhou"

                imported_result = await vault.load_model_async(version=imported, use_cache=False)
                assert imported_result is not None
                assert imported_result[1] == (await vault.load_model_async(version=versions[0], use_cache=False))[1]

                progress.update(task, advance=1)

                # Teste 5: cleanup/arquivamento
                task = progress.add_task("[red]Testando arquivamento...", total=1)
                await vault._cleanup_old_versions_async()
                remaining = await vault._list_versions_async({"archived": False})
                assert len(remaining) <= vault.max_versions, "Cleanup não respeitou max_versions"
                progress.update(task, advance=1)

    console.print("\n[bold green]✅ TODOS OS TESTES PASSARAM COM SUCESSO![/]\n")
    return 0


# ─── Entry Point ────────────────────────────────────────────────────────────
async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ATENA Memory Vault v3.1 - Sistema de Versionamento de Modelos"
    )
    parser.add_argument('--test', action='store_true', help='Executa testes')
    parser.add_argument('--serve', action='store_true', help='Inicia servidor API')
    parser.add_argument('--host', default='0.0.0.0', help='Host do servidor')
    parser.add_argument('--port', type=int, default=8000, help='Porta do servidor')
    parser.add_argument('--metrics-port', type=int, default=9090, help='Porta de métricas Prometheus')

    args = parser.parse_args()

    if args.test:
        return await run_advanced_tests()

    if args.serve:
        from prometheus_client import start_http_server
        from hypercorn.asyncio import serve as hypercorn_serve
        from hypercorn.config import Config as HypercornConfig
        import multiprocessing

        start_http_server(args.metrics_port)

        async with AtenaMemoryVault() as vault:
            app = create_app(vault)

            config = HypercornConfig()
            config.bind = [f"{args.host}:{args.port}"]
            config.workers = multiprocessing.cpu_count()

            logger.info("starting_server", host=args.host, port=args.port)
            await hypercorn_serve(app, config)

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
        sys.exit(0)
    except Exception as e:
        logger.exception("fatal_error", error=str(e))
        sys.exit(1)
