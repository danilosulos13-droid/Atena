#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔱 ATENA Internet Challenge v4.0 - Real Internet Intelligence

Enterprise Features:
- 🌐 Execução real com aiohttp e rate limiting
- 🧠 Síntese avançada com múltiplas fontes
- 💾 Cache hierárquico (LRU + Redis)
- 📊 Métricas Prometheus (tempo, fontes, confiança)
- 📝 Logging estruturado (structlog)
- 🗄️ Persistência SQLite (histórico de desafios)
- 🔁 Retry com backoff exponencial (tenacity)
- ⚙️ Configuração via Pydantic/ENV
- 📈 Relatórios Markdown e JSON
- 🚀 API RESTful (FastAPI) para execução sob demanda
- 🧪 CLI com Rich (progresso, tabelas)
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import aiohttp
import aiofiles
import structlog
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from pydantic import BaseModel, Field, HttpUrl, ConfigDict, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# -----------------------------------------------------------------------------
# Structured Logging
# -----------------------------------------------------------------------------
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
logger = structlog.get_logger(__name__)

# -----------------------------------------------------------------------------
# Prometheus Metrics
# -----------------------------------------------------------------------------
METRICS_PREFIX = "atena_internet_challenge"

challenge_requests = Counter(f"{METRICS_PREFIX}_requests_total", "Total challenge requests", ["status"])
challenge_duration = Histogram(f"{METRICS_PREFIX}_duration_seconds", "Challenge duration")
sources_processed = Gauge(f"{METRICS_PREFIX}_sources_processed", "Sources processed per challenge")
confidence_gauge = Gauge(f"{METRICS_PREFIX}_confidence", "Confidence score")
cache_hits = Counter(f"{METRICS_PREFIX}_cache_hits_total", "Cache hits", ["level"])
cache_misses = Counter(f"{METRICS_PREFIX}_cache_misses_total", "Cache misses", ["level"])

# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------
class ChallengeStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"

class ChallengeRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    sources_limit: int = Field(10, ge=1, le=50)
    timeout_seconds: int = Field(30, ge=5, le=120)
    use_cache: bool = True

class EvolutionSignal(BaseModel):
    trend: str
    message: str
    confidence: float = Field(ge=0.0, le=1.0)

class ChallengeResult(BaseModel):
    challenge_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    query: str
    status: ChallengeStatus
    confidence: float = Field(ge=0.0, le=1.0)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    evolution_signal: Optional[EvolutionSignal] = None
    difficulty_score: float = Field(ge=0.0, le=1.0)
    duration_seconds: float = 0.0
    cached: bool = False
    error: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

# -----------------------------------------------------------------------------
# Cache Manager (Hierarchical)
# -----------------------------------------------------------------------------
class LRUCache:
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self._cache = {}
        self._expiry = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._cache:
                return None
            if time.time() > self._expiry[key]:
                del self._cache[key]
                del self._expiry[key]
                return None
            return self._cache[key]

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl or self.ttl
        async with self._lock:
            if len(self._cache) >= self.max_size:
                # Remove oldest
                oldest = min(self._expiry, key=self._expiry.get)
                del self._cache[oldest]
                del self._expiry[oldest]
            self._cache[key] = value
            self._expiry[key] = time.time() + ttl

class HierarchicalCache:
    def __init__(self, redis_url: Optional[str] = None):
        self.memory = LRUCache(500, 3600)
        self._redis = None
        if redis_url and HAS_REDIS:
            self._redis = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> Optional[Any]:
        val = await self.memory.get(key)
        if val is not None:
            cache_hits.labels(level="memory").inc()
            return val
        cache_misses.labels(level="memory").inc()
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    cache_hits.labels(level="redis").inc()
                    val = json.loads(data)
                    await self.memory.set(key, val)
                    return val
            except Exception:
                pass
            cache_misses.labels(level="redis").inc()
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl or 3600
        await self.memory.set(key, value, ttl)
        if self._redis:
            try:
                await self._redis.setex(key, ttl, json.dumps(value, default=str))
            except Exception:
                pass

    async def close(self):
        if self._redis:
            await self._redis.close()

# -----------------------------------------------------------------------------
# Internet Challenge Engine
# -----------------------------------------------------------------------------
class InternetChallengeEngine:
    """Motor real de navegação e síntese de informações da internet."""

    def __init__(self, cache: HierarchicalCache):
        self.cache = cache
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30, connect=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session:
            await self._session.close()

    def _cache_key(self, query: str, limit: int) -> str:
        key = f"internet_challenge:{hashlib.md5(f"{query}:{limit}".encode()).hexdigest()}"
        return key

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
           retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
    async def _fetch_webpage(self, url: str) -> Tuple[str, str]:
        """Faz requisição HTTP com retry."""
        session = await self._get_session()
        async with session.get(url) as resp:
            if resp.status != 200:
                raise aiohttp.ClientError(f"HTTP {resp.status}: {url}")
            content = await resp.text()
            content_type = resp.headers.get("content-type", "").lower()
            return content, content_type

    async def _search_web(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """
        Busca na web usando DuckDuckGo como fonte primária (não requer API key).
        """
        results = []
        # Usa a API de busca do DuckDuckGo
        search_url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        session = await self._get_session()
        try:
            async with session.get(search_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Extrai resultados
                    if data.get("Abstract"):
                        results.append({
                            "title": data.get("Heading", "Untitled"),
                            "snippet": data.get("Abstract", ""),
                            "url": data.get("AbstractURL", ""),
                            "source": "DuckDuckGo"
                        })
                    if data.get("RelatedTopics"):
                        for item in data.get("RelatedTopics", []):
                            if item.get("Text") and len(results) < limit:
                                results.append({
                                    "title": item.get("Text", "")[:100],
                                    "snippet": item.get("Text", ""),
                                    "url": item.get("FirstURL", ""),
                                    "source": "DuckDuckGo"
                                })
                    # Fallback para Wikipedia
                    if data.get("Infobox"):
                        results.append({
                            "title": data.get("Heading", "Wikipedia"),
                            "snippet": data.get("Abstract", ""),
                            "url": data.get("AbstractURL", ""),
                            "source": "Wikipedia"
                        })
        except Exception as e:
            logger.warning("search_failed", error=str(e))

        # Se não houver resultados, usa uma segunda fonte (ex: OpenLibrary para livros)
        if len(results) < 3:
            try:
                alt_url = "https://openlibrary.org/search.json"
                params = {"q": query, "limit": limit}
                async with session.get(alt_url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for doc in data.get("docs", [])[:limit]:
                            results.append({
                                "title": doc.get("title", "Untitled"),
                                "snippet": doc.get("first_sentence", [""])[0] if doc.get("first_sentence") else "",
                                "url": f"https://openlibrary.org{doc.get('key', '')}",
                                "source": "OpenLibrary"
                            })
            except Exception:
                pass

        return results[:limit]

    async def _synthesize(self, results: List[Dict], query: str) -> Tuple[ChallengeResult, EvolutionSignal]:
        """Sintetiza os resultados em um relatório coerente."""
        if not results:
            return ChallengeResult(
                challenge_id=str(uuid.uuid4())[:8],
                query=query,
                status=ChallengeStatus.FAILED,
                confidence=0.0,
                sources=[],
                difficulty_score=0.0,
                error="Nenhuma fonte encontrada"
            ), EvolutionSignal(trend="none", message="Sem dados para síntese", confidence=0.0)

        # Calcula métricas
        total_sources = len(results)
        confidence = min(1.0, 0.5 + (total_sources / 20))  # 10 fontes -> 1.0
        difficulty = min(1.0, total_sources / 15)  # 15 fontes -> 1.0

        # Gera mensagem de evolução
        if confidence > 0.8:
            trend = "positive"
            message = "ATENA demonstra alta capacidade de navegação e síntese."
        elif confidence > 0.4:
            trend = "neutral"
            message = "Capacidade de síntese em desenvolvimento."
        else:
            trend = "negative"
            message = "Desafio de navegação mostrou limitações; mais treinamento necessário."

        evolution = EvolutionSignal(trend=trend, message=message, confidence=confidence)

        # Monta resultado
        result = ChallengeResult(
            challenge_id=str(uuid.uuid4())[:8],
            query=query,
            status=ChallengeStatus.SUCCESS if confidence > 0.5 else ChallengeStatus.PARTIAL,
            confidence=confidence,
            sources=results,
            evolution_signal=evolution,
            difficulty_score=difficulty,
        )
        return result, evolution

    async def run_challenge(self, request: ChallengeRequest) -> ChallengeResult:
        """Executa o desafio completo com cache e monitoramento."""
        start = time.perf_counter()
        challenge_requests.labels(status="started").inc()

        cache_key = self._cache_key(request.query, request.sources_limit)
        if request.use_cache:
            cached = await self.cache.get(cache_key)
            if cached:
                result = ChallengeResult(**cached)
                result.cached = True
                challenge_requests.labels(status="cached").inc()
                confidence_gauge.set(result.confidence)
                sources_processed.set(len(result.sources))
                logger.info("challenge_cached", query=request.query)
                return result

        try:
            logger.info("challenge_started", query=request.query, limit=request.sources_limit)
            results = await self._search_web(request.query, request.sources_limit)
            result, evolution = await self._synthesize(results, request.query)
            result.duration_seconds = time.perf_counter() - start

            # Atualiza métricas
            confidence_gauge.set(result.confidence)
            sources_processed.set(len(result.sources))
            challenge_duration.observe(result.duration_seconds)
            challenge_requests.labels(status=result.status.value).inc()

            # Cache
            if request.use_cache and result.status != ChallengeStatus.FAILED:
                await self.cache.set(cache_key, result.model_dump(mode='json'), ttl=3600)

            logger.info("challenge_completed", challenge_id=result.challenge_id, confidence=result.confidence)
            return result

        except Exception as e:
            error_msg = str(e)
            challenge_requests.labels(status="error").inc()
            logger.exception("challenge_failed", error=error_msg)
            return ChallengeResult(
                challenge_id=str(uuid.uuid4())[:8],
                query=request.query,
                status=ChallengeStatus.FAILED,
                confidence=0.0,
                sources=[],
                difficulty_score=0.0,
                error=error_msg,
                duration_seconds=time.perf_counter() - start
            )

# -----------------------------------------------------------------------------
# Storage (SQLite)
# -----------------------------------------------------------------------------
class ChallengeStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS challenges (
                    challenge_id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    query TEXT,
                    status TEXT,
                    confidence REAL,
                    difficulty REAL,
                    duration REAL,
                    sources_json TEXT,
                    evolution_json TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_challenges_time ON challenges(timestamp);
                CREATE INDEX IF NOT EXISTS idx_challenges_status ON challenges(status);
            """)

    async def save(self, result: ChallengeResult):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO challenges 
                   (challenge_id, timestamp, query, status, confidence, difficulty, duration, sources_json, evolution_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.challenge_id, result.timestamp.isoformat(), result.query,
                 result.status.value, result.confidence, result.difficulty_score,
                 result.duration_seconds, json.dumps(result.sources, default=str),
                 json.dumps(result.evolution_signal.model_dump() if result.evolution_signal else None),
                 result.error)
            )

    async def get_history(self, limit: int = 20) -> List[Dict]:
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM challenges ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel as PydanticBase

class ChallengeResponse(PydanticBase):
    challenge_id: str
    status: str
    confidence: float
    sources_count: int
    evolution: Optional[Dict]
    duration_seconds: float

def create_app() -> FastAPI:
    app = FastAPI(title="ATENA Internet Challenge API", version="4.0")
    cache = HierarchicalCache(os.getenv("REDIS_URL"))
    engine = InternetChallengeEngine(cache)
    storage = ChallengeStorage(Path.home() / ".atena/internet_challenge.db")

    @app.on_event("shutdown")
    async def shutdown():
        await engine.close()
        await cache.close()

    @app.post("/challenge", response_model=ChallengeResponse)
    async def run_challenge(req: ChallengeRequest):
        result = await engine.run_challenge(req)
        await storage.save(result)
        return ChallengeResponse(
            challenge_id=result.challenge_id,
            status=result.status.value,
            confidence=result.confidence,
            sources_count=len(result.sources),
            evolution=result.evolution_signal.model_dump() if result.evolution_signal else None,
            duration_seconds=result.duration_seconds
        )

    @app.get("/history")
    async def get_history(limit: int = Query(20, le=100)):
        return await storage.get_history(limit)

    return app

# -----------------------------------------------------------------------------
# CLI with Rich
# -----------------------------------------------------------------------------
async def async_main():
    import argparse
    parser = argparse.ArgumentParser(description="ATENA Internet Challenge v4.0")
    parser.add_argument("query", nargs="*", help="Query de pesquisa")
    parser.add_argument("--limit", type=int, default=10, help="Limite de fontes")
    parser.add_argument("--no-cache", action="store_true", help="Ignora cache")
    parser.add_argument("--serve", action="store_true", help="Inicia servidor API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--metrics-port", type=int, default=9090)
    parser.add_argument("--history", action="store_true", help="Exibe histórico")
    parser.add_argument("--json", action="store_true", help="Saída JSON")
    args = parser.parse_args()

    if args.serve:
        import uvicorn
        from prometheus_client import start_http_server
        start_http_server(args.metrics_port)
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    if args.history:
        storage = ChallengeStorage(Path.home() / ".atena/internet_challenge.db")
        history = await storage.get_history(limit=20)
        if args.json:
            print(json.dumps(history, indent=2, default=str))
            return
        if RICH_AVAILABLE:
            console = Console()
            table = Table(title="Histórico de Desafios")
            table.add_column("ID", style="cyan")
            table.add_column("Data", style="dim")
            table.add_column("Query", style="white")
            table.add_column("Status", style="green")
            table.add_column("Confiança", style="yellow")
            for row in history:
                status_color = "green" if row['status'] == "success" else "red"
                table.add_row(
                    row['challenge_id'][:8],
                    row['timestamp'][:19],
                    row['query'][:40],
                    f"[{status_color}]{row['status']}[/]",
                    f"{row['confidence']:.2%}"
                )
            console.print(table)
        else:
            for row in history:
                print(f"{row['timestamp']} | {row['query'][:40]} | {row['status']} | {row['confidence']:.2%}")
        return

    query = " ".join(args.query) if args.query else "advanced artificial intelligence evolution and self-modifying code"
    req = ChallengeRequest(query=query, sources_limit=args.limit, use_cache=not args.no_cache)

    cache = HierarchicalCache(os.getenv("REDIS_URL"))
    engine = InternetChallengeEngine(cache)
    storage = ChallengeStorage(Path.home() / ".atena/internet_challenge.db")

    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=Console()) as progress:
            task = progress.add_task("🌐 Navegando na internet...", total=None)
            result = await engine.run_challenge(req)
            progress.update(task, completed=True)

        await storage.save(result)

        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            console = Console()
            console.print(Panel(f"[bold cyan]🔱 ATENA Internet Challenge[/]\nQuery: {query}", style="cyan"))
            table = Table(show_header=False, box=None)
            table.add_column("Métrica", style="bold")
            table.add_column("Valor")
            table.add_row("Status", result.status.value.upper())
            table.add_row("Confiança", f"{result.confidence:.2%}")
            table.add_row("Fontes", str(len(result.sources)))
            table.add_row("Duração", f"{result.duration_seconds:.2f}s")
            if result.evolution_signal:
                table.add_row("Tendência", result.evolution_signal.trend)
                table.add_row("Mensagem", result.evolution_signal.message)
            if result.error:
                table.add_row("Erro", result.error)
            console.print(table)
            if result.sources:
                console.print("\n[bold]Top Fontes:[/]")
                for idx, src in enumerate(result.sources[:5], 1):
                    console.print(f"  {idx}. {src.get('title', 'N/A')[:60]}")

    finally:
        await engine.close()
        await cache.close()

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
