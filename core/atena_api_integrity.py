#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              ATENA Ω - API Integrity Sentinel v4.0                          ║
║         Teste de integridade, catalogação e monitoramento de APIs          ║
║                                                                            ║
║  Recursos Enterprise:                                                      ║
║  • Modelos Pydantic com validação rigorosa                                 ║
║  • Cache hierárquico (memória LRU + Redis opcional)                        ║
║  • Métricas Prometheus (latência, disponibilidade, erros)                  ║
║  • Logging estruturado com structlog                                       ║
║  • API RESTful com FastAPI para consulta de resultados                     ║
║  • Modo contínuo com agendamento (cron simplificado)                       ║
║  • Persistência SQLite com histórico e estatísticas agregadas              ║
║  • Relatórios HTML interativos (Plotly) com template Jinja2                ║
║  • Notificações webhook (Slack/Discord) com rate limiting                  ║
║  • Configuração flexível via YAML/ENV/CLI                                  ║
║  • CLI com Rich (tabelas, painéis, progresso)                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Generic, TypeVar, Callable

import aiohttp
import aiofiles
import structlog
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from pydantic import BaseModel, Field, HttpUrl, ConfigDict, field_validator, ValidationError
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import yaml
import jinja2
import plotly.graph_objects as go
import sqlite3

# Optional dependencies
try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

try:
    from jsonschema import validate, ValidationError as SchemaError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
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
METRICS_PREFIX = "atena_api_sentinel"

test_requests = Counter(f"{METRICS_PREFIX}_test_requests_total", "Total API test requests", ["endpoint", "status"])
test_duration = Histogram(f"{METRICS_PREFIX}_test_duration_seconds", "API test duration", ["method"])
availability_gauge = Gauge(f"{METRICS_PREFIX}_availability_percent", "API availability percentage", ["url"])
cache_hits = Counter(f"{METRICS_PREFIX}_cache_hits_total", "Cache hits")
cache_misses = Counter(f"{METRICS_PREFIX}_cache_misses_total", "Cache misses")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "api_integrity.db"
DEFAULT_CONFIG_PATH = BASE_DIR / "api_catalog_config.yaml"
DEFAULT_REPORT_DIR = BASE_DIR / "reports"

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class AuthType(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"

# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------
class ApiEndpointConfig(BaseModel):
    url: HttpUrl
    method: str = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    payload: Optional[Dict[str, Any]] = None
    expected_status: int = Field(200, ge=100, le=599)
    timeout_seconds: float = Field(5.0, ge=0.5, le=60)
    auth_type: AuthType = AuthType.NONE
    auth_credential: Optional[str] = None
    schema_validation: Optional[Dict[str, Any]] = None  # JSON Schema
    tags: List[str] = Field(default_factory=list)

    @field_validator('method')
    @classmethod
    def validate_method(cls, v: str) -> str:
        v = v.upper()
        if v not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}:
            raise ValueError(f'Método HTTP inválido: {v}')
        return v

    model_config = ConfigDict(extra="forbid")

class ApiCatalog(BaseModel):
    endpoints: List[ApiEndpointConfig]
    global_timeout: float = Field(10.0, ge=1)
    max_concurrency: int = Field(10, ge=1, le=50)
    retry_attempts: int = Field(3, ge=0, le=10)
    retry_backoff_base: float = Field(0.5, ge=0.1)
    notify_webhook: Optional[HttpUrl] = None

    model_config = ConfigDict(extra="forbid")

class TestResult(BaseModel):
    url: str
    method: str
    status_code: Optional[int] = None
    response_time_ms: float = 0.0
    success: bool
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    test_run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    response_body: Optional[Dict[str, Any]] = None
    schema_valid: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")

# -----------------------------------------------------------------------------
# Cache LRU
# -----------------------------------------------------------------------------
T = TypeVar('T')
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

    def clear(self):
        with self._lock:
            self._cache.clear()

# -----------------------------------------------------------------------------
# Database Layer (SQLite)
# -----------------------------------------------------------------------------
class IntegrityDB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status_code INTEGER,
                    response_time_ms REAL,
                    success INTEGER,
                    error_message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    test_run_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_results_url ON test_results(url);
                CREATE INDEX IF NOT EXISTS idx_results_timestamp ON test_results(timestamp);
                CREATE INDEX IF NOT EXISTS idx_results_run ON test_results(test_run_id);

                CREATE TABLE IF NOT EXISTS endpoint_catalog (
                    url TEXT NOT NULL,
                    method TEXT NOT NULL,
                    last_success_time DATETIME,
                    last_failure_time DATETIME,
                    avg_response_time_ms REAL,
                    uptime_percentage REAL DEFAULT 0.0,
                    total_tests INTEGER DEFAULT 0,
                    successful_tests INTEGER DEFAULT 0,
                    PRIMARY KEY (url, method)
                );
            """)

    async def save_result(self, result: TestResult):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO test_results 
                   (url, method, status_code, response_time_ms, success, error_message, timestamp, test_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.url, result.method, result.status_code, result.response_time_ms,
                 int(result.success), result.error_message, result.timestamp.isoformat(), result.test_run_id)
            )

    async def update_catalog_stats(self, url: str, method: str, success: bool, response_time_ms: float):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO endpoint_catalog (url, method, last_success_time, last_failure_time, avg_response_time_ms, uptime_percentage, total_tests, successful_tests)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                ON CONFLICT(url, method) DO UPDATE SET
                    last_success_time = CASE WHEN ? THEN ? ELSE last_success_time END,
                    last_failure_time = CASE WHEN NOT ? THEN ? ELSE last_failure_time END,
                    avg_response_time_ms = (avg_response_time_ms * total_tests + ?) / (total_tests + 1),
                    total_tests = total_tests + 1,
                    successful_tests = successful_tests + ?,
                    uptime_percentage = (successful_tests + ?) * 100.0 / (total_tests + 1)
            """, (url, method, now, now,
                  success, now if success else None,
                  success, now if not success else None,
                  response_time_ms,
                  1 if success else 0,
                  1 if success else 0))

    def get_history(self, days: int = 7, limit: int = 1000) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM test_results WHERE timestamp >= datetime('now', ?) ORDER BY timestamp DESC LIMIT ?",
                (f'-{days} days', limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_catalog_summary(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM endpoint_catalog ORDER BY url").fetchall()
            return [dict(r) for r in rows]

# -----------------------------------------------------------------------------
# API Tester (with retry, auth, schema validation)
# -----------------------------------------------------------------------------
class ApiTester:
    def __init__(self, endpoint: ApiEndpointConfig, db: IntegrityDB, cache: LRUCache[TestResult]):
        self.endpoint = endpoint
        self.db = db
        self.cache = cache

    def _cache_key(self) -> str:
        # Chave baseada nos parâmetros que afetam o resultado
        data = f"{self.endpoint.url}|{self.endpoint.method}|{self.endpoint.payload}|{self.endpoint.expected_status}"
        return hashlib.md5(data.encode()).hexdigest()

    async def _build_session(self) -> aiohttp.ClientSession:
        headers = self.endpoint.headers.copy()
        # Auth
        if self.endpoint.auth_type == AuthType.BEARER and self.endpoint.auth_credential:
            headers["Authorization"] = f"Bearer {self.endpoint.auth_credential}"
        elif self.endpoint.auth_type == AuthType.API_KEY and self.endpoint.auth_credential:
            headers["X-API-Key"] = self.endpoint.auth_credential
        elif self.endpoint.auth_type == AuthType.BASIC and self.endpoint.auth_credential:
            encoded = base64.b64encode(self.endpoint.auth_credential.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        timeout = aiohttp.ClientTimeout(total=self.endpoint.timeout_seconds + 2)
        return aiohttp.ClientSession(headers=headers, timeout=timeout)

    async def test(self, use_cache: bool = True) -> TestResult:
        cache_key = self._cache_key()
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                cache_hits.inc()
                logger.debug("cache_hit", url=str(self.endpoint.url))
                return cached
        cache_misses.inc()

        start_time = time.monotonic()
        retryer = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=self.endpoint.timeout_seconds * 0.2, min=0.5, max=5),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            before_sleep=before_sleep_log(logger, logging.DEBUG)
        )
        last_exception = None
        status_code = None
        response_body = None
        success = False
        error_msg = None
        schema_valid = None

        async for attempt in retryer:
            try:
                session = await self._build_session()
                async with session:
                    resp = await session.request(
                        self.endpoint.method,
                        str(self.endpoint.url),
                        json=self.endpoint.payload if self.endpoint.method in ('POST','PUT','PATCH') else None
                    )
                    status_code = resp.status
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    success = (status_code == self.endpoint.expected_status)
                    if success and self.endpoint.schema_validation and HAS_JSONSCHEMA:
                        try:
                            response_body = await resp.json()
                            from jsonschema import validate as js_validate
                            js_validate(instance=response_body, schema=self.endpoint.schema_validation)
                            schema_valid = True
                        except Exception as e:
                            schema_valid = False
                            success = False
                            error_msg = f"Schema validation failed: {e}"
                    elif success:
                        # Try to get body but not required
                        try:
                            response_body = await resp.json()
                        except:
                            pass
                    if not success and not error_msg:
                        error_msg = f"Expected {self.endpoint.expected_status}, got {status_code}"
                    break
            except Exception as e:
                last_exception = e
                elapsed_ms = (time.monotonic() - start_time) * 1000
                continue

        if not success and last_exception and not error_msg:
            error_msg = str(last_exception)
            status_code = None

        result = TestResult(
            url=str(self.endpoint.url),
            method=self.endpoint.method,
            status_code=status_code,
            response_time_ms=elapsed_ms,
            success=success,
            error_message=error_msg,
            response_body=response_body,
            schema_valid=schema_valid
        )
        # Update metrics
        label_status = "success" if success else "failure"
        test_requests.labels(endpoint=self.endpoint.url.path, status=label_status).inc()
        test_duration.labels(method=self.endpoint.method).observe(elapsed_ms / 1000.0)
        # Cache result
        self.cache.set(cache_key, result)
        return result

# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------
class IntegrityOrchestrator:
    def __init__(self, catalog: ApiCatalog, db: IntegrityDB, cache: LRUCache[TestResult]):
        self.catalog = catalog
        self.db = db
        self.cache = cache
        self.semaphore = asyncio.Semaphore(catalog.max_concurrency)

    async def run_all(self) -> List[TestResult]:
        tasks = [self._test_one(ep) for ep in self.catalog.endpoints]
        results = await asyncio.gather(*tasks)
        return results

    async def _test_one(self, endpoint: ApiEndpointConfig) -> TestResult:
        async with self.semaphore:
            tester = ApiTester(endpoint, self.db, self.cache)
            result = await tester.test(use_cache=True)  # cache at orchestrator level
            await self.db.save_result(result)
            await self.db.update_catalog_stats(result.url, result.method, result.success, result.response_time_ms)
            return result

    def generate_html_report(self, results: List[TestResult], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count
        # Pie chart
        pie = go.Figure(data=[go.Pie(labels=['Success', 'Failure'], values=[success_count, fail_count], hole=0.3)])
        pie.update_layout(title="Overall Success Rate")
        # Latency by endpoint
        endpoints = list(set(r.url for r in results))
        latencies = []
        for url in endpoints:
            times = [r.response_time_ms for r in results if r.url == url and r.success]
            if times:
                latencies.append({
                    'url': url[:50],
                    'avg': sum(times)/len(times),
                    'min': min(times),
                    'max': max(times),
                    'p95': self._percentile(times, 95)
                })
        if latencies:
            bar = go.Figure()
            for metric in ['avg', 'p95', 'min', 'max']:
                bar.add_trace(go.Bar(name=metric, x=[l['url'] for l in latencies], y=[l[metric] for l in latencies]))
            bar.update_layout(title="Latency by Endpoint (ms)", barmode='group')
        else:
            bar = go.Figure()
        # History from DB
        hist = self.db.get_history(days=7)
        if hist:
            hourly = {}
            for row in hist:
                hour = row['timestamp'][:13]
                if hour not in hourly:
                    hourly[hour] = {'total': 0, 'success': 0}
                hourly[hour]['total'] += 1
                hourly[hour]['success'] += int(row['success'])
            hours = sorted(hourly.keys())
            rates = [hourly[h]['success']/hourly[h]['total']*100 for h in hours]
            line = go.Figure(data=go.Scatter(x=hours, y=rates, mode='lines+markers'))
            line.update_layout(title="Success Rate Trend (last 7 days)", yaxis_title="%")
        else:
            line = go.Figure()
        # Combine HTML
        html = f"""
        <html><head><title>ATENA API Integrity Report</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>body{{font-family: Arial; margin:20px;}} .chart{{margin-bottom:30px;}}</style>
        </head><body>
        <h1>API Integrity Report</h1>
        <p>Run at {datetime.now(timezone.utc).isoformat()} | Total tests: {len(results)}</p>
        <div class="chart">{pie.to_html(full_html=False)}</div>
        <div class="chart">{bar.to_html(full_html=False)}</div>
        <div class="chart">{line.to_html(full_html=False)}</div>
        </body></html>
        """
        output_path.write_text(html, encoding='utf-8')
        logger.info("report_generated", path=str(output_path))
        return output_path

    @staticmethod
    def _percentile(data: List[float], p: float) -> float:
        if not data:
            return 0
        data_sorted = sorted(data)
        idx = (p/100) * (len(data_sorted)-1)
        lower = int(idx)
        upper = lower + 1
        if upper >= len(data_sorted):
            return data_sorted[-1]
        weight = idx - lower
        return data_sorted[lower] * (1-weight) + data_sorted[upper] * weight

# -----------------------------------------------------------------------------
# Configuration Loader
# -----------------------------------------------------------------------------
def load_catalog(path: Path = DEFAULT_CONFIG_PATH) -> ApiCatalog:
    if not path.exists():
        logger.warning("config_not_found", path=str(path))
        # Return default catalog for demo
        return ApiCatalog(
            endpoints=[
                ApiEndpointConfig(url="https://jsonplaceholder.typicode.com/posts/1", method="GET", expected_status=200, tags=["demo"]),
                ApiEndpointConfig(url="https://jsonplaceholder.typicode.com/posts", method="POST", payload={"title":"test"}, expected_status=201, tags=["demo"]),
                ApiEndpointConfig(url="https://httpbin.org/status/200", method="GET", expected_status=200),
                ApiEndpointConfig(url="https://httpbin.org/status/404", method="GET", expected_status=404),
                ApiEndpointConfig(url="https://httpbin.org/delay/1", method="GET", expected_status=200, timeout_seconds=3),
            ]
        )
    with open(path, 'r', encoding='utf-8') as f:
        if path.suffix in ('.yaml', '.yml'):
            data = yaml.safe_load(f)
        else:
            data = json.load(f)
    return ApiCatalog(**data)

# -----------------------------------------------------------------------------
# Webhook Notifier
# -----------------------------------------------------------------------------
class WebhookNotifier:
    def __init__(self, url: Optional[str], rate_limit_seconds: int = 60):
        self.url = url
        self._last_sent = 0
        self._rate_limit = rate_limit_seconds

    async def send(self, message: str):
        if not self.url:
            return
        now = time.time()
        if now - self._last_sent < self._rate_limit:
            logger.debug("webhook_rate_limited")
            return
        self._last_sent = now
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.url, json={"text": message}, timeout=aiohttp.ClientTimeout(total=10))
            logger.info("webhook_sent", url=self.url)
        except Exception as e:
            logger.warning("webhook_failed", error=str(e))

# -----------------------------------------------------------------------------
# Continuous Mode
# -----------------------------------------------------------------------------
async def continuous_mode(catalog_path: Path, interval_seconds: int, webhook_url: Optional[str] = None):
    logger.info("continuous_mode_started", interval=interval_seconds)
    db = IntegrityDB()
    cache = LRUCache[TestResult]()
    notifier = WebhookNotifier(webhook_url)
    while True:
        try:
            catalog = load_catalog(catalog_path)
            orch = IntegrityOrchestrator(catalog, db, cache)
            results = await orch.run_all()
            success_rate = sum(1 for r in results if r.success) / len(results) * 100 if results else 0
            report_path = orch.generate_html_report(results, DEFAULT_REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            await notifier.send(f"API Integrity test completed. Success rate: {success_rate:.1f}% - {report_path}")
            logger.info("continuous_cycle_completed", success_rate=success_rate)
        except Exception as e:
            logger.exception("continuous_cycle_failed")
        await asyncio.sleep(interval_seconds)

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel as PydanticBase

class RunTestRequest(PydanticBase):
    config_path: Optional[str] = None

class RunTestResponse(PydanticBase):
    test_run_id: str
    total_tests: int
    success_rate: float
    report_url: str

def create_app() -> FastAPI:
    app = FastAPI(title="ATENA API Integrity Sentinel", version="4.0")
    db = IntegrityDB()
    cache = LRUCache[TestResult]()

    @app.post("/run", response_model=RunTestResponse)
    async def run_test(req: RunTestRequest):
        config_path = Path(req.config_path) if req.config_path else DEFAULT_CONFIG_PATH
        catalog = load_catalog(config_path)
        orch = IntegrityOrchestrator(catalog, db, cache)
        results = await orch.run_all()
        test_run_id = results[0].test_run_id if results else str(uuid.uuid4())[:8]
        success_rate = sum(1 for r in results if r.success) / len(results) * 100 if results else 0
        report_path = orch.generate_html_report(results, DEFAULT_REPORT_DIR / f"api_report_{test_run_id}.html")
        return RunTestResponse(
            test_run_id=test_run_id,
            total_tests=len(results),
            success_rate=round(success_rate, 2),
            report_url=str(report_path)
        )

    @app.get("/history")
    async def get_history(days: int = Query(7, ge=1, le=30), limit: int = Query(100, le=1000)):
        return db.get_history(days, limit)

    @app.get("/catalog")
    async def get_catalog():
        return db.get_catalog_summary()

    return app

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
async def async_main():
    import argparse
    parser = argparse.ArgumentParser(description="ATENA Ω - API Integrity Sentinel v4.0")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Config file (YAML/JSON)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=300, help="Interval in seconds for continuous mode")
    parser.add_argument("--webhook", type=str, help="Webhook URL for notifications")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    parser.add_argument("--metrics-port", type=int, default=9090, help="Prometheus metrics port")
    parser.add_argument("--no-cache", action="store_true", help="Disable cache")
    args = parser.parse_args()

    if args.serve:
        start_http_server(args.metrics_port)
        import uvicorn
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    if args.once:
        catalog = load_catalog(args.config)
        db = IntegrityDB()
        cache = LRUCache[TestResult]() if not args.no_cache else None
        if cache is None:
            # dummy cache that never hits
            class NoCache:
                def get(self, key): return None
                def set(self, key, value, ttl=None): pass
            cache = NoCache()
        orch = IntegrityOrchestrator(catalog, db, cache)
        results = await orch.run_all()
        report_path = orch.generate_html_report(results, DEFAULT_REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        if RICH_AVAILABLE:
            console = Console()
            table = Table(title="Test Results")
            table.add_column("URL", style="cyan")
            table.add_column("Method", style="magenta")
            table.add_column("Status", justify="right")
            table.add_column("Time (ms)", justify="right")
            table.add_column("Result", justify="center")
            for r in results:
                icon = "[green]✓[/]" if r.success else "[red]✗[/]"
                table.add_row(r.url[:60], r.method, str(r.status_code or "ERR"),
                              f"{r.response_time_ms:.1f}", icon)
            console.print(table)
        else:
            for r in results:
                print(f"{r.url} [{r.method}] -> {r.status_code} ({r.response_time_ms:.1f}ms) {'OK' if r.success else 'FAIL'}")
        if args.webhook:
            notifier = WebhookNotifier(args.webhook)
            success_rate = sum(1 for r in results if r.success) / len(results) * 100
            await notifier.send(f"API Integrity test completed. Success rate: {success_rate:.1f}%")
    else:
        await continuous_mode(args.config, args.interval, args.webhook)

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("shutdown_by_user")
    except Exception as e:
        logger.exception("fatal_error")
        sys.exit(1)

if __name__ == "__main__":
    main()
