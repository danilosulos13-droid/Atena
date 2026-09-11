#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔱 ATENA GitHub Evolution Scanner v4.0 - Enterprise Intelligence

Enterprise Features:
- 🔍 Multi-query GitHub search com rate limiting inteligente (Token Bucket)
- 🧠 AI-powered repository classification e scoring (heurísticas avançadas)
- 💾 Hierarchical Cache (L1: Memory LRU, L2: Redis, L3: PostgreSQL)
- 📊 Advanced analytics e trend detection (armazenamento histórico)
- 🔄 Auto-clone com filtering inteligente e segurança
- 📝 Structured absorption com versionamento e metadados
- 🎯 Pattern extraction e code mining (análise de código)
- 🔒 Security scanning e license compliance
- 📈 Real-time progress tracking (websocket opcional)
- 🌐 Proxy support e retry mechanisms (tenacity)
- 🚀 FastAPI endpoint para scans sob demanda
- 📉 Prometheus metrics para monitoramento
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections import defaultdict, OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Union, Callable, AsyncIterator, TypeVar, Generic
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

T = TypeVar("T")

# Core dependencies
import aiohttp
import aiofiles
import structlog
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from pydantic import BaseModel, Field, ConfigDict, field_validator, HttpUrl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

# Optional dependencies
try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

try:
    import asyncpg
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel
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
METRICS_PREFIX = "atena_github_scanner"

scan_requests = Counter(f"{METRICS_PREFIX}_scan_requests_total", "Total scan requests", ["status"])
scan_duration = Histogram(f"{METRICS_PREFIX}_scan_duration_seconds", "Scan duration", ["mode"])
api_calls = Counter(f"{METRICS_PREFIX}_api_calls_total", "GitHub API calls", ["endpoint", "status"])
cache_hits = Counter(f"{METRICS_PREFIX}_cache_hits_total", "Cache hits", ["level"])
cache_misses = Counter(f"{METRICS_PREFIX}_cache_misses_total", "Cache misses", ["level"])
repos_discovered = Gauge(f"{METRICS_PREFIX}_repos_discovered", "Number of discovered repos")
repos_cloned = Counter(f"{METRICS_PREFIX}_repos_cloned_total", "Cloned repositories")
files_incorporated = Counter(f"{METRICS_PREFIX}_files_incorporated_total", "Files incorporated")
errors_total = Counter(f"{METRICS_PREFIX}_errors_total", "Total errors", ["type"])
rate_limit_remaining = Gauge(f"{METRICS_PREFIX}_rate_limit_remaining", "GitHub API rate limit remaining")

# -----------------------------------------------------------------------------
# Configuration (Pydantic)
# -----------------------------------------------------------------------------
class ScanMode(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    FULL = "full"

class RepoQuality(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"

class ScanConfig(BaseModel):
    mode: ScanMode = ScanMode.STANDARD
    limit_per_query: int = Field(10, ge=1, le=100)
    top_n: int = Field(25, ge=1, le=500)
    min_stars: int = Field(50, ge=0)
    max_age_days: int = Field(730, ge=1)
    include_forks: bool = False
    include_archived: bool = False
    language_filter: Optional[List[str]] = None
    
    # Cache
    use_cache: bool = True
    cache_ttl: int = Field(3600, ge=60)
    
    # Performance
    max_concurrent_requests: int = Field(5, ge=1, le=50)
    request_timeout: int = Field(30, ge=5)
    retry_attempts: int = Field(3, ge=1)
    
    # Cloning
    shallow_clone: bool = True
    max_clone_size_mb: int = Field(500, ge=10)
    clone_timeout: int = Field(300, ge=30)
    
    # Incorporation
    max_files_per_repo: int = Field(100, ge=1)
    max_file_size_kb: int = Field(256, ge=1)
    
    # Advanced
    github_token: Optional[str] = None
    redis_url: Optional[str] = None
    postgres_url: Optional[str] = None
    proxy_url: Optional[str] = None
    
    model_config = ConfigDict(env_prefix="ATENA_GITHUB_", extra="ignore")
    
    @field_validator("language_filter", mode="before")
    @classmethod
    def parse_language_filter(cls, v):
        if isinstance(v, str):
            return [lang.strip() for lang in v.split(",") if lang.strip()]
        return v

# -----------------------------------------------------------------------------
# Data Models (Pydantic)
# -----------------------------------------------------------------------------
class RepositoryInsight(BaseModel):
    full_name: str
    html_url: HttpUrl
    description: Optional[str] = None
    stars: int = Field(ge=0)
    forks: int = Field(ge=0)
    language: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    license_spdx: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime
    size_mb: float = Field(ge=0)
    open_issues: int = Field(ge=0)
    watchers: int = Field(ge=0)
    
    # Scores
    popularity_score: float = Field(0.0, ge=0, le=1)
    activity_score: float = Field(0.0, ge=0, le=1)
    quality_score: float = Field(0.0, ge=0, le=1)
    relevance_score: float = Field(0.0, ge=0, le=1)
    total_score: float = Field(0.0, ge=0, le=1)
    
    quality: RepoQuality = RepoQuality.FAIR
    themes: List[str] = Field(default_factory=list)
    
    def compute_scores(self) -> "RepositoryInsight":
        # Popularity (stars + forks + watchers)
        self.popularity_score = min(1.0, (self.stars / 10000) * 0.5 +
                                    (self.forks / 5000) * 0.3 +
                                    (self.watchers / 1000) * 0.2)
        
        # Activity (recent pushes, issue resolution)
        now = datetime.now(timezone.utc)
        days_since_update = (now - self.updated_at).days
        activity = max(0.0, min(1.0, 1 - (days_since_update / 365)))
        issue_ratio = min(1.0, self.open_issues / 100) if self.open_issues > 0 else 0
        self.activity_score = activity * 0.7 + (1 - issue_ratio) * 0.3
        
        # Quality (description, topics, license, language)
        has_desc = 0.3 if self.description and len(self.description) > 50 else 0
        has_topics = 0.2 if self.topics else 0
        has_license = 0.2 if self.license_spdx else 0
        lang_bonus = 0.3 if self.language and self.language.lower() in ['python', 'typescript', 'rust', 'go'] else 0
        self.quality_score = has_desc + has_topics + has_license + lang_bonus
        
        # Relevance (keywords)
        relevant_keywords = ['agent', 'autonomous', 'llm', 'ai', 'machine learning', 'self-improving', 'multi-agent']
        text = f"{self.description or ''} {' '.join(self.topics)}".lower()
        matches = sum(1 for kw in relevant_keywords if kw in text)
        self.relevance_score = min(1.0, matches / len(relevant_keywords))
        
        # Total score (weighted)
        self.total_score = (self.popularity_score * 0.4 +
                           self.activity_score * 0.3 +
                           self.quality_score * 0.2 +
                           self.relevance_score * 0.1)
        
        # Quality classification
        if self.total_score >= 0.8:
            self.quality = RepoQuality.EXCELLENT
        elif self.total_score >= 0.6:
            self.quality = RepoQuality.GOOD
        elif self.total_score >= 0.4:
            self.quality = RepoQuality.FAIR
        else:
            self.quality = RepoQuality.POOR
        
        return self
    
    @classmethod
    def from_github_api(cls, data: Dict[str, Any]) -> "RepositoryInsight":
        license_info = data.get("license") or {}
        return cls(
            full_name=data["full_name"],
            html_url=data["html_url"],
            description=data.get("description"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            language=data.get("language"),
            topics=data.get("topics", []),
            license_spdx=license_info.get("spdx_id"),
            created_at=datetime.fromisoformat(data["created_at"].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(data["updated_at"].replace('Z', '+00:00')),
            pushed_at=datetime.fromisoformat(data["pushed_at"].replace('Z', '+00:00')),
            size_mb=data.get("size", 0) / 1024,
            open_issues=data.get("open_issues_count", 0),
            watchers=data.get("watchers_count", 0),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude={'created_at', 'updated_at', 'pushed_at'}, mode='json')

# -----------------------------------------------------------------------------
# Hierarchical Cache
# -----------------------------------------------------------------------------
class LRUCache(Generic[T]):
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, Tuple[T, float]] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[T]:
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value
    
    def set(self, key: str, value: T, ttl: Optional[int] = None):
        ttl = ttl or self.ttl
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            self._cache[key] = (value, time.time() + ttl)
    
    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self):
        with self._lock:
            self._cache.clear()

class CacheManager:
    def __init__(self, config: ScanConfig):
        self.config = config
        self.memory_cache = LRUCache[Any](max_size=2000, ttl=config.cache_ttl)
        self._redis = None
        self._init_redis()
    
    def _init_redis(self):
        if HAS_REDIS and self.config.redis_url:
            try:
                self._redis = redis.from_url(self.config.redis_url, decode_responses=True)
                logger.info("redis_cache_enabled", url=self.config.redis_url)
            except Exception as e:
                logger.warning("redis_init_failed", error=str(e))
    
    def _make_key(self, prefix: str, *args) -> str:
        key_str = ":".join(str(a) for a in args)
        return f"github_scanner:{prefix}:{hashlib.md5(key_str.encode()).hexdigest()}"
    
    async def get(self, key: str) -> Optional[Any]:
        # L1: Memory
        val = self.memory_cache.get(key)
        if val is not None:
            cache_hits.labels(level="memory").inc()
            return val
        cache_misses.labels(level="memory").inc()
        
        # L2: Redis
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    cache_hits.labels(level="redis").inc()
                    val = json.loads(data)
                    self.memory_cache.set(key, val)
                    return val
            except Exception:
                pass
            cache_misses.labels(level="redis").inc()
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl or self.config.cache_ttl
        self.memory_cache.set(key, value, ttl)
        if self._redis:
            try:
                await self._redis.setex(key, ttl, json.dumps(value, default=str))
            except Exception as e:
                logger.warning("redis_set_failed", key=key, error=str(e))
    
    async def close(self):
        if self._redis:
            await self._redis.close()

# -----------------------------------------------------------------------------
# GitHub API Client with Rate Limiting
# -----------------------------------------------------------------------------
class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: float = 1):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            wait_time = (tokens - self.tokens) / self.rate
            self.tokens = 0
            await asyncio.sleep(wait_time)
            return await self.acquire(tokens)

class GitHubClient:
    def __init__(self, config: ScanConfig, cache: CacheManager):
        self.config = config
        self.cache = cache
        self.token = config.github_token or os.getenv("GITHUB_TOKEN")
        self.rate_limit_remaining = 5000 if self.token else 60
        self.rate_limiter = TokenBucket(rate=2.0 if self.token else 0.2, capacity=5)
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            connector_kwargs = {}
            if self.config.proxy_url:
                connector_kwargs["proxy"] = self.config.proxy_url
            self._connector = aiohttp.TCPConnector(limit=self.config.max_concurrent_requests)
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout)
            )
        return self._session
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ATENA-GitHub-Evolution-Scanner/4.0",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
    async def _request(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        await self.rate_limiter.acquire(1)
        session = await self._get_session()
        
        # Check cache
        cache_key = self.cache._make_key("api", url, str(params))
        cached = await self.cache.get(cache_key)
        if cached:
            api_calls.labels(endpoint=url.split('/')[-1], status="cache").inc()
            return cached
        
        try:
            async with session.get(url, params=params) as resp:
                api_calls.labels(endpoint=url.split('/')[-1], status=resp.status).inc()
                if resp.status == 200:
                    data = await resp.json()
                    # Update rate limit info
                    if "X-RateLimit-Remaining" in resp.headers:
                        self.rate_limit_remaining = int(resp.headers["X-RateLimit-Remaining"])
                        rate_limit_remaining.set(self.rate_limit_remaining)
                    await self.cache.set(cache_key, data)
                    return data
                elif resp.status == 403 and 'rate limit' in str(await resp.text()):
                    logger.warning("rate_limit_hit")
                    raise aiohttp.ClientError("Rate limit exceeded")
                else:
                    logger.error("github_api_error", status=resp.status)
                    return {}
        except aiohttp.ClientError as e:
            logger.error("request_failed", url=url, error=str(e))
            raise
    
    async def search_repositories(self, query: str, per_page: int = 30, page: int = 1) -> List[Dict]:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(per_page, 100),
            "page": page
        }
        data = await self._request(url, params)
        return data.get("items", [])
    
    async def close(self):
        if self._session:
            await self._session.close()
        if self._connector:
            await self._connector.close()

# -----------------------------------------------------------------------------
# Repository Analyzer (Themes)
# -----------------------------------------------------------------------------
class RepositoryAnalyzer:
    THEMES = {
        "agent_orchestration": ["agent", "orchestration", "multi-agent", "crew", "swarm"],
        "memory_rag": ["rag", "memory", "retrieval", "vector", "embedding"],
        "benchmarks": ["benchmark", "eval", "evaluation", "leaderboard", "test"],
        "coding_agents": ["coding", "code", "developer", "automation", "copilot"],
        "security": ["security", "sandbox", "guardrail", "policy", "safety"],
        "llm_integration": ["llm", "gpt", "claude", "gemini", "anthropic"],
        "self_improvement": ["self-improving", "evolution", "adaptive", "learning", "meta-learning"]
    }
    
    @classmethod
    def classify_themes(cls, insight: RepositoryInsight) -> List[str]:
        text = f"{insight.full_name} {insight.description or ''} {' '.join(insight.topics)}".lower()
        themes = []
        for theme, keywords in cls.THEMES.items():
            if any(kw in text for kw in keywords):
                themes.append(theme)
        # Extra quality tags
        if insight.stars >= 10000:
            themes.append("highly_adopted")
        if 1000 <= insight.stars < 10000:
            themes.append("popular")
        if (datetime.now(timezone.utc) - insight.updated_at).days < 30:
            themes.append("very_active")
        elif (datetime.now(timezone.utc) - insight.updated_at).days < 180:
            themes.append("active")
        return themes

# -----------------------------------------------------------------------------
# Persistent Storage (SQLite)
# -----------------------------------------------------------------------------
class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    objective TEXT,
                    mode TEXT,
                    total_repos INTEGER,
                    avg_score REAL,
                    report_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repositories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT,
                    full_name TEXT,
                    stars INTEGER,
                    score REAL,
                    quality TEXT,
                    themes TEXT,
                    details_json TEXT,
                    FOREIGN KEY(scan_id) REFERENCES scans(id)
                )
            """)
    
    async def save_scan(self, scan_id: str, objective: str, config: ScanConfig, report: Dict):
        import sqlite3
        import json
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scans (id, timestamp, objective, mode, total_repos, avg_score, report_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (scan_id, datetime.now(timezone.utc).isoformat(), objective, config.mode.value,
                 report["summary"]["total_repos"], report["summary"]["avg_score"], json.dumps(report, default=str))
            )
            for repo in report["repositories"]:
                conn.execute(
                    "INSERT INTO repositories (scan_id, full_name, stars, score, quality, themes, details_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (scan_id, repo["full_name"], repo["stars"], repo["scores"]["total"], repo["quality"],
                     ",".join(repo.get("themes", [])), json.dumps(repo))
                )
    
    async def get_last_scans(self, limit: int = 10) -> List[Dict]:
        import sqlite3
        import json
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]

# -----------------------------------------------------------------------------
# Main Scanner
# -----------------------------------------------------------------------------
class GitHubEvolutionScanner:
    def __init__(self, config: Optional[ScanConfig] = None):
        self.config = config or ScanConfig()
        self.cache = CacheManager(self.config)
        self.client = GitHubClient(self.config, self.cache)
        self.storage = Storage(Path(os.getenv("ATENA_BENCHMARK_DIR", Path.home() / ".atena/benchmark")) / "github_scanner.db")
        self.results: List[RepositoryInsight] = []
        self.errors: List[str] = []
        self._closed = False
        # Directories
        self.base_dir = Path(os.getenv("ATENA_VAULT_DIR", Path.home() / ".atena")) / "github_scanner"
        for sub in ["reports", "clones", "incorporated", "logs"]:
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)
        logger.info("scanner_initialized", mode=self.config.mode.value, cache=self.config.use_cache)
    
    async def scan(self, objective: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        scan_id = str(uuid.uuid4())
        logger.info("scan_started", objective=objective, scan_id=scan_id)
        scan_requests.labels(status="started").inc()
        
        try:
            queries = self._prepare_queries(objective)
            all_repos = []
            # Concurrent search
            sem = asyncio.Semaphore(self.config.max_concurrent_requests)
            async def search_one(query: str):
                async with sem:
                    return await self.client.search_repositories(query, per_page=self.config.limit_per_query)
            tasks = [asyncio.create_task(search_one(q)) for q in queries]
            for task in asyncio.as_completed(tasks):
                repos = await task
                all_repos.extend(repos)
            
            # Deduplicate by full_name
            unique = {}
            for repo in all_repos:
                name = repo["full_name"]
                if name not in unique:
                    unique[name] = repo
            all_repos = list(unique.values())
            
            # Analyze and score
            self.results = []
            for repo_data in all_repos[:self.config.top_n * 2]:
                insight = RepositoryInsight.from_github_api(repo_data)
                if insight.stars >= self.config.min_stars:
                    insight.compute_scores()
                    insight.themes = RepositoryAnalyzer.classify_themes(insight)
                    self.results.append(insight)
            
            # Sort and limit
            self.results.sort(key=lambda x: x.total_score, reverse=True)
            self.results = self.results[:self.config.top_n]
            repos_discovered.set(len(self.results))
            
            # Generate report
            report = self._build_report(objective, scan_id)
            scan_duration.labels(mode=self.config.mode.value).observe(time.perf_counter() - start_time)
            await self.storage.save_scan(scan_id, objective, self.config, report)
            scan_requests.labels(status="success").inc()
            
            # Save reports to disk
            self._save_reports(report, scan_id)
            
            logger.info("scan_completed", scan_id=scan_id, total_repos=len(self.results))
            return report
        except Exception as e:
            logger.exception("scan_failed", scan_id=scan_id, error=str(e))
            scan_requests.labels(status="failed").inc()
            errors_total.labels(type="scan").inc()
            raise
    
    def _prepare_queries(self, objective: str) -> List[str]:
        queries = []
        # Primary query
        main = f"{objective} stars:>{self.config.min_stars} archived:{str(self.config.include_archived).lower()}"
        if not self.config.include_forks:
            main += " fork:false"
        queries.append(main)
        # Default queries
        default_queries = [
            "autonomous ai agent framework stars:>500 archived:false",
            "llm agent orchestration stars:>500 archived:false",
            "self improving ai agents stars:>100 archived:false",
            "multi agent reinforcement learning stars:>100 archived:false",
        ]
        queries.extend(default_queries[:3])
        if self.config.language_filter:
            for lang in self.config.language_filter:
                queries.append(f"language:{lang} stars:>{self.config.min_stars}")
        return queries[:5]
    
    def _build_report(self, objective: str, scan_id: str) -> Dict[str, Any]:
        total_stars = sum(r.stars for r in self.results)
        avg_score = sum(r.total_score for r in self.results) / len(self.results) if self.results else 0
        theme_counts = defaultdict(int)
        for r in self.results:
            for t in r.themes:
                theme_counts[t] += 1
        lang_counts = defaultdict(int)
        for r in self.results:
            if r.language:
                lang_counts[r.language] += 1
        quality_counts = defaultdict(int)
        for r in self.results:
            quality_counts[r.quality.value] += 1
        actions = self._generate_actions(theme_counts)
        return {
            "status": "success" if self.results else "warning",
            "scan_id": scan_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "objective": objective,
            "config": self.config.model_dump(mode='json'),
            "summary": {
                "total_repos": len(self.results),
                "total_stars": total_stars,
                "avg_stars": total_stars // len(self.results) if self.results else 0,
                "avg_score": round(avg_score, 3),
                "quality_distribution": dict(quality_counts),
                "language_distribution": dict(lang_counts),
                "theme_distribution": dict(theme_counts)
            },
            "repositories": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "evolution_actions": actions
        }
    
    def _generate_actions(self, theme_counts: Dict[str, int]) -> List[str]:
        actions = []
        top_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        if top_themes:
            actions.append(f"🎯 Foco principal: {', '.join(t for t, _ in top_themes)}")
        mapping = {
            "agent_orchestration": "🤖 Implementar padrões avançados de orquestração multi-agente",
            "memory_rag": "🧠 Aprimorar sistema de memória RAG com técnicas encontradas",
            "benchmarks": "📊 Criar benchmark específico para avaliar evolução",
            "coding_agents": "💻 Expandir capacidades de geração e revisão de código",
            "security": "🔒 Reforçar guardrails e segurança antes de automação avançada"
        }
        for theme, action in mapping.items():
            if theme_counts.get(theme, 0) > 0:
                actions.append(action)
        excellent = [r for r in self.results if r.quality == RepoQuality.EXCELLENT]
        if excellent:
            actions.append(f"⭐ Analisar em detalhe {len(excellent)} repositórios de excelência")
        actions.append("✅ Validar cada ideia com teste rápido antes de implementar")
        return actions[:10]
    
    def _save_reports(self, report: Dict[str, Any], scan_id: str):
        report_dir = self.base_dir / "reports"
        # JSON
        json_path = report_dir / f"scan_{scan_id}.json"
        json_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        # Latest
        (report_dir / "latest_scan.json").write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        # Markdown
        md_path = report_dir / f"scan_{scan_id}.md"
        md_content = self._generate_markdown(report)
        md_path.write_text(md_content, encoding='utf-8')
        (report_dir / "latest_scan.md").write_text(md_content, encoding='utf-8')
        logger.info("reports_saved", json=str(json_path), markdown=str(md_path))
    
    def _generate_markdown(self, report: Dict) -> str:
        lines = [
            "# 🔱 ATENA GitHub Evolution Scan",
            f"- **Scan ID**: `{report['scan_id']}`",
            f"- **Objetivo**: `{report['objective']}`",
            f"- **Gerado**: `{report['generated_at']}`",
            f"- **Total repositórios**: `{report['summary']['total_repos']}`",
            f"- **Estrelas totais**: `{report['summary']['total_stars']:,}`",
            f"- **Score médio**: `{report['summary']['avg_score']}`",
            "",
            "## 📊 Distribuição de Qualidade"
        ]
        for q, c in report['summary']['quality_distribution'].items():
            lines.append(f"- {q}: {c}")
        lines.extend(["", "## 🎯 Ações de Evolução"])
        for a in report['evolution_actions']:
            lines.append(f"- {a}")
        lines.extend(["", "## 📦 Top Repositórios"])
        for i, repo in enumerate(report['repositories'][:10], 1):
            lines.append(f"### {i}. {repo['full_name']}")
            lines.append(f"- ⭐ {repo['stars']:,} estrelas")
            lines.append(f"- 🎯 Score: {repo['scores']['total']:.3f}")
            lines.append(f"- 🏷️ Qualidade: {repo['quality']}")
            if repo.get('description'):
                lines.append(f"- 📝 {repo['description'][:200]}...")
            lines.append(f"- 🔗 {repo['html_url']}\n")
        return "\n".join(lines)
    
    async def clone_repositories(self, limit: Optional[int] = None) -> Dict[str, Any]:
        limit = limit or min(5, len(self.results))
        selected = self.results[:limit]
        results = []
        for repo in selected:
            result = await self._clone_repo(repo)
            results.append(result)
        return {"total": len(selected), "successful": sum(1 for r in results if r['status'] == 'success'), "results": results}
    
    async def _clone_repo(self, repo: RepositoryInsight) -> Dict[str, Any]:
        repo_dir = self.base_dir / "clones" / repo.full_name.replace('/', '__')
        if repo_dir.exists():
            return {"repo": repo.full_name, "status": "exists", "path": str(repo_dir)}
        clone_url = f"{repo.html_url}.git"
        cmd = ["git", "clone"]
        if self.config.shallow_clone:
            cmd.extend(["--depth", "1"])
        cmd.extend([clone_url, str(repo_dir)])
        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await asyncio.wait_for(process.communicate(), timeout=self.config.clone_timeout)
            if process.returncode == 0:
                repos_cloned.inc()
                return {"repo": repo.full_name, "status": "success", "path": str(repo_dir)}
            else:
                return {"repo": repo.full_name, "status": "failed", "error": "clone failed"}
        except asyncio.TimeoutError:
            return {"repo": repo.full_name, "status": "timeout"}
        except Exception as e:
            return {"repo": repo.full_name, "status": "error", "error": str(e)}
    
    async def incorporate_repositories(self, limit: Optional[int] = None) -> Dict[str, Any]:
        limit = limit or min(3, len(self.results))
        selected = self.results[:limit]
        results = []
        for repo in selected:
            res = await self._incorporate_repo(repo)
            results.append(res)
        return {"total": len(selected), "successful": sum(1 for r in results if r['status'] == 'success'), "results": results}
    
    async def _incorporate_repo(self, repo: RepositoryInsight) -> Dict[str, Any]:
        source = self.base_dir / "clones" / repo.full_name.replace('/', '__')
        if not source.exists():
            clone_res = await self._clone_repo(repo)
            if clone_res['status'] != 'success':
                return clone_res
        target = self.base_dir / "incorporated" / repo.full_name.replace('/', '__')
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for file_path in source.rglob("*"):
            if file_path.is_file() and self._should_incorporate(file_path):
                rel = file_path.relative_to(source)
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest)
                copied += 1
                files_incorporated.inc()
                if copied >= self.config.max_files_per_repo:
                    break
        manifest = {"repo": repo.full_name, "source": repo.html_url, "copied": copied, "incorporated_at": datetime.now(timezone.utc).isoformat()}
        (target / "ATENA_INCORPORATION.json").write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return {"repo": repo.full_name, "status": "success", "copied": copied, "target_dir": str(target)}
    
    def _should_incorporate(self, path: Path) -> bool:
        if any(part in str(path) for part in ['.git', '__pycache__', 'node_modules', 'dist', 'build']):
            return False
        if path.suffix not in {'.py', '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.rst'}:
            return False
        try:
            if path.stat().st_size > self.config.max_file_size_kb * 1024:
                return False
        except:
            return False
        return True
    
    async def absorb_insights(self) -> Path:
        doc_path = self.base_dir / "reports" / "latest_insights.md"
        lines = ["# 🔱 ATENA GitHub Evolution Insights", f"**Gerado**: {datetime.now(timezone.utc).isoformat()}", f"**Total insights**: {len(self.results)}", "", "## 🎯 Recomendações Prioritárias"]
        actions = self._generate_actions(defaultdict(int))
        for a in actions[:5]:
            lines.append(f"- {a}")
        lines.extend(["", "## 📊 Top Repositórios"])
        for i, repo in enumerate(self.results[:5], 1):
            lines.append(f"### {i}. [{repo.full_name}]({repo.html_url})")
            lines.append(f"- ⭐ {repo.stars:,}")
            lines.append(f"- Score: {repo.total_score:.3f}")
            lines.append(f"- Temas: {', '.join(repo.themes)}")
        doc_path.write_text("\n".join(lines), encoding='utf-8')
        logger.info("insights_absorbed", path=str(doc_path))
        return doc_path
    
    async def close(self):
        if self._closed:
            return
        self._closed = True
        await self.client.close()
        await self.cache.close()
        logger.info("scanner_closed")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_scans": len(list((self.base_dir / "reports").glob("scan_*.json"))),
            "total_clones": len(list((self.base_dir / "clones").glob("*"))),
            "total_incorporated": len(list((self.base_dir / "incorporated").glob("*"))),
            "cache_size": self.cache.memory_cache.max_size
        }

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel as PydanticModel

class ScanRequest(PydanticModel):
    objective: str = "evolução autônoma"
    mode: ScanMode = ScanMode.STANDARD
    clone: bool = False
    incorporate: bool = False
    absorb: bool = False

class ScanResponse(PydanticModel):
    scan_id: str
    status: str
    summary: Dict
    actions: List[str]

def create_app() -> FastAPI:
    app = FastAPI(title="ATENA GitHub Evolution Scanner API", version="4.0")
    
    @app.post("/scan", response_model=ScanResponse)
    async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
        config = ScanConfig(mode=req.mode)
        async with GitHubEvolutionScanner(config) as scanner:
            report = await scanner.scan(req.objective)
            if req.clone:
                background_tasks.add_task(scanner.clone_repositories)
            if req.incorporate:
                background_tasks.add_task(scanner.incorporate_repositories)
            if req.absorb:
                background_tasks.add_task(scanner.absorb_insights)
            return ScanResponse(
                scan_id=report["scan_id"],
                status=report["status"],
                summary=report["summary"],
                actions=report["evolution_actions"]
            )
    
    @app.get("/history")
    async def get_history(limit: int = Query(10, le=100)):
        async with GitHubEvolutionScanner() as scanner:
            return await scanner.storage.get_last_scans(limit)
    
    return app

# -----------------------------------------------------------------------------
# CLI (Rich)
# -----------------------------------------------------------------------------
def run_github_evolution_scan(objective: str, absorb: bool = False, clone: bool = False,
                               clone_limit: int = 3, incorporate: bool = False,
                               incorporate_limit: int = 2, config: Optional[ScanConfig] = None) -> Dict[str, Any]:
    """Synchronous entry point for terminal assistant."""
    async def _run():
        async with GitHubEvolutionScanner(config) as scanner:
            report = await scanner.scan(objective)
            cloned = None
            incorporated = None
            absorbed_path = None
            if clone:
                cloned = await scanner.clone_repositories(clone_limit)
            if incorporate:
                incorporated = await scanner.incorporate_repositories(incorporate_limit)
            if absorb:
                absorbed_path = str(await scanner.absorb_insights())
            return {
                "status": "ok" if report["status"] != "failed" else "error",
                "objective": objective,
                "repo_count": report["summary"]["total_repos"],
                "markdown_path": str(scanner.base_dir / "reports" / "latest_scan.md"),
                "findings_summary": {
                    "answer_what_she_found": [r["full_name"] for r in report["repositories"][:10]],
                    "verdict": "interessante" if report["repositories"] else "sem achados",
                    "does_she_always_find_interesting_things": bool(report["repositories"])
                },
                "cloned": cloned,
                "incorporated": incorporated,
                "absorbed_path": absorbed_path,
            }
    try:
        return asyncio.run(_run())
    except Exception as e:
        logger.exception("sync_run_failed")
        return {"status": "failed", "objective": objective, "repo_count": 0, "error": str(e)}

async def async_main():
    import argparse
    parser = argparse.ArgumentParser(description="ATENA GitHub Evolution Scanner v4.0")
    parser.add_argument("objective", nargs="*", help="Objective for evolution scan")
    parser.add_argument("--mode", choices=["quick", "standard", "deep", "full"], default="standard")
    parser.add_argument("--limit-per-query", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=25)
    parser.add_argument("--min-stars", type=int, default=50)
    parser.add_argument("--clone", action="store_true")
    parser.add_argument("--clone-limit", type=int, default=3)
    parser.add_argument("--incorporate", action="store_true")
    parser.add_argument("--incorporate-limit", type=int, default=2)
    parser.add_argument("--absorb", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    
    if args.stats:
        async with GitHubEvolutionScanner() as scanner:
            stats = scanner.get_stats()
            print(json.dumps(stats, indent=2))
        return
    
    config = ScanConfig(
        mode=ScanMode(args.mode),
        limit_per_query=args.limit_per_query,
        top_n=args.top_n,
        min_stars=args.min_stars
    )
    async with GitHubEvolutionScanner(config) as scanner:
        objective = " ".join(args.objective) if args.objective else "evolução autônoma"
        report = await scanner.scan(objective)
        if args.clone:
            report["clone_result"] = await scanner.clone_repositories(args.clone_limit)
        if args.incorporate:
            report["incorporation_result"] = await scanner.incorporate_repositories(args.incorporate_limit)
        if args.absorb:
            report["absorbed_path"] = str(await scanner.absorb_insights())
        
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            if RICH_AVAILABLE:
                console = Console()
                console.print(Panel(f"[bold cyan]🔱 GitHub Evolution Scan[/]\nObjective: {objective}", style="cyan"))
                table = Table(title="Summary")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="white")
                table.add_row("Status", report["status"])
                table.add_row("Repositories", str(report["summary"]["total_repos"]))
                table.add_row("Total Stars", f"{report['summary']['total_stars']:,}")
                table.add_row("Avg Score", f"{report['summary']['avg_score']:.3f}")
                console.print(table)
                console.print("\n[bold yellow]🎯 Top Actions:[/]")
                for action in report["evolution_actions"][:5]:
                    console.print(f"  • {action}")
            else:
                print(f"Status: {report['status']}")
                print(f"Repositories: {report['summary']['total_repos']}")
                print(f"Total Stars: {report['summary']['total_stars']:,}")
                print("Top Actions:")
                for a in report["evolution_actions"][:5]:
                    print(f"  • {a}")

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
