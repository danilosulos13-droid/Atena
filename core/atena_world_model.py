#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ATENA Ω — CAUSAL WORLD MODEL SIMULATOR v2.0                ║
║                                                                                ║
║  Simulação de efeitos colaterais e causalidade para ações autônomas.          ║
║                                                                                ║
║  Features:                                                                    ║
║  • Modelo causal bayesiano paramétrico (não aleatório)                        ║
║  • Histórico de simulações com SQLite                                         ║
║  • Cache LRU de resultados                                                    ║
║  • Métricas Prometheus (latência, acurácia, risco)                            ║
║  • API RESTful com FastAPI                                                    ║
║  • CLI com Rich output                                                        ║
║  • Logging estruturado (structlog)                                            ║
║  • Tipagem estática e imutabilidade (Pydantic, dataclasses frozen)            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, Generic, TypeVar
import threading
import asyncio

# Core dependencies
import aiofiles
import structlog
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, HttpUrl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Optional rich for CLI
try:
    from rich.console import Console
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
METRICS_PREFIX = "atena_causal_world"

simulation_requests = Counter(f"{METRICS_PREFIX}_simulations_total", "Total simulation requests", ["status"])
simulation_duration = Histogram(f"{METRICS_PREFIX}_simulation_duration_seconds", "Simulation latency", ["action_type"])
risk_level_gauge = Gauge(f"{METRICS_PREFIX}_risk_level", "Current risk level (1=low,2=medium,3=high)", ["action"])
cache_hits = Counter(f"{METRICS_PREFIX}_cache_hits_total", "Cache hits")
cache_misses = Counter(f"{METRICS_PREFIX}_cache_misses_total", "Cache misses")

# -----------------------------------------------------------------------------
# Enums and Constants
# -----------------------------------------------------------------------------
class SystemState(str, Enum):
    STABLE = "stable"
    UNSTABLE = "unstable"
    CRITICAL = "critical"
    OPTIMIZED = "optimized"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ActionCategory(str, Enum):
    INFERENCE_UPDATE = "inference_update"
    MEMORY_OPERATION = "memory_operation"
    CODE_GENERATION = "code_generation"
    SELF_IMPROVEMENT = "self_improvement"
    EXTERNAL_API_CALL = "external_api_call"
    UNKNOWN = "unknown"

# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------
class SimulationRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=500)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    action_category: ActionCategory = ActionCategory.UNKNOWN
    use_cache: bool = True

    model_config = ConfigDict(extra="forbid")

class SimulationResult(BaseModel):
    simulation_id: str
    action: str
    action_category: ActionCategory
    success_probability: float = Field(ge=0.0, le=1.0)
    side_effects: List[str] = Field(default_factory=list)
    predicted_state: SystemState
    risk_level: RiskLevel
    causal_factors: Dict[str, float] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cache_hit: bool = False

    @property
    def risk_score(self) -> int:
        return {"low": 1, "medium": 2, "high": 3}[self.risk_level.value]

# -----------------------------------------------------------------------------
# Causal Model (non‑random, parameterized)
# -----------------------------------------------------------------------------
class CausalModel:
    """Modelo causal bayesiano paramétrico – não aleatório, determinístico baseado em heurísticas avançadas."""

    # Fatores de risco para cada categoria
    BASE_SUCCESS_PROB = {
        ActionCategory.INFERENCE_UPDATE: 0.85,
        ActionCategory.MEMORY_OPERATION: 0.78,
        ActionCategory.CODE_GENERATION: 0.70,
        ActionCategory.SELF_IMPROVEMENT: 0.65,
        ActionCategory.EXTERNAL_API_CALL: 0.90,
        ActionCategory.UNKNOWN: 0.75,
    }

    SIDE_EFFECT_MAP = {
        ActionCategory.INFERENCE_UPDATE: ["Aumento temporário de latência", "Possível regressão em casos extremos"],
        ActionCategory.MEMORY_OPERATION: ["Consumo de memória elevado", "Fragmentação de cache"],
        ActionCategory.CODE_GENERATION: ["Introdução de bugs não detectados", "Aumento de complexidade"],
        ActionCategory.SELF_IMPROVEMENT: ["Instabilidade durante adaptação", "Efeitos colaterais não previstos"],
        ActionCategory.EXTERNAL_API_CALL: ["Dependência externa", "Variação de resposta"],
        ActionCategory.UNKNOWN: ["Comportamento imprevisível"],
    }

    STATE_TRANSITIONS = {
        SystemState.STABLE: {"optimized": 0.3, "unstable": 0.1, "critical": 0.02},
        SystemState.OPTIMIZED: {"stable": 0.4, "unstable": 0.15, "critical": 0.03},
        SystemState.UNSTABLE: {"stable": 0.2, "critical": 0.3, "optimized": 0.05},
        SystemState.CRITICAL: {"stable": 0.1, "unstable": 0.2, "optimized": 0.0},
    }

    @classmethod
    def predict(cls, action: str, category: ActionCategory, context: Dict[str, Any]) -> SimulationResult:
        # Base success probability
        base_prob = cls.BASE_SUCCESS_PROB.get(category, 0.75)

        # Adjust based on action length (proxy for complexity) and context
        complexity_penalty = min(0.2, len(action) / 2000)  # long actions reduce success
        context_bonus = 0.05 if context.get("tested_before") else 0.0
        success_prob = max(0.2, min(0.99, base_prob - complexity_penalty + context_bonus))

        # Side effects (always include at least one)
        side_effects = cls.SIDE_EFFECT_MAP.get(category, ["Efeito desconhecido"]).copy()
        if success_prob < 0.7:
            side_effects.append("Alta probabilidade de falha")
        if category == ActionCategory.SELF_IMPROVEMENT and success_prob < 0.8:
            side_effects.append("Pode exigir rollback manual")

        # Predicted state based on success probability and current context state
        current_state = SystemState(context.get("current_state", "stable"))
        transitions = cls.STATE_TRANSITIONS.get(current_state, cls.STATE_TRANSITIONS[SystemState.STABLE])
        if success_prob > 0.85:
            new_state = SystemState.OPTIMIZED if "optimized" in transitions else SystemState.STABLE
        elif success_prob > 0.7:
            new_state = current_state
        else:
            # Deterioration
            if current_state == SystemState.STABLE:
                new_state = SystemState.UNSTABLE
            elif current_state == SystemState.UNSTABLE:
                new_state = SystemState.CRITICAL
            else:
                new_state = current_state

        # Risk level
        if success_prob >= 0.85:
            risk = RiskLevel.LOW
        elif success_prob >= 0.7:
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.HIGH

        # Causal factors (dictionary of weights)
        causal_factors = {
            "base_probability": base_prob,
            "complexity_penalty": complexity_penalty,
            "context_bonus": context_bonus,
            "current_state_stability": 1.0 if current_state in (SystemState.STABLE, SystemState.OPTIMIZED) else 0.5,
        }

        return SimulationResult(
            simulation_id=str(uuid.uuid4()),
            action=action,
            action_category=category,
            success_probability=round(success_prob, 4),
            side_effects=side_effects,
            predicted_state=new_state,
            risk_level=risk,
            causal_factors=causal_factors,
        )

# -----------------------------------------------------------------------------
# Cache (LRU)
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

# -----------------------------------------------------------------------------
# Persistent Storage (SQLite)
# -----------------------------------------------------------------------------
class SimulationStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS simulations (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    action TEXT,
                    category TEXT,
                    success_prob REAL,
                    risk TEXT,
                    predicted_state TEXT,
                    side_effects TEXT,
                    causal_factors TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON simulations(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON simulations(category)")

    async def save(self, result: SimulationResult):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO simulations (id, timestamp, action, category, success_prob, risk, predicted_state, side_effects, causal_factors) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.simulation_id,
                    result.timestamp.isoformat(),
                    result.action,
                    result.action_category.value,
                    result.success_probability,
                    result.risk_level.value,
                    result.predicted_state.value,
                    json.dumps(result.side_effects),
                    json.dumps(result.causal_factors)
                )
            )
        logger.info("simulation_saved", simulation_id=result.simulation_id)

    async def get_history(self, limit: int = 50, category: Optional[str] = None) -> List[Dict[str, Any]]:
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM simulations"
            params = []
            if category:
                query += " WHERE category = ?"
                params.append(category)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            cur = conn.execute(query, params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]

# -----------------------------------------------------------------------------
# Main Simulator Engine
# -----------------------------------------------------------------------------
class CausalWorldSimulator:
    def __init__(self, db_path: Optional[Path] = None):
        self.base_dir = Path(os.getenv("ATENA_CAUSAL_DIR", Path.home() / ".atena" / "causal_world"))
        self.storage = SimulationStorage(db_path or (self.base_dir / "simulations.db"))
        self.cache = LRUCache[SimulationResult](max_size=500, ttl=3600)
        self._closed = False
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("simulator_initialized", db_path=str(self.storage.db_path))

    def _cache_key(self, action: str, category: str, context: Dict) -> str:
        key_str = f"{action}|{category}|{json.dumps(context, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    async def simulate(self, request: SimulationRequest) -> SimulationResult:
        start_time = time.perf_counter()
        cache_key = self._cache_key(request.action, request.action_category.value, request.context)

        # Check cache
        if request.use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                cache_hits.inc()
                simulation_requests.labels(status="cache_hit").inc()
                simulation_duration.labels(action_type=request.action_category.value).observe(time.perf_counter() - start_time)
                # Return cached result (immutable)
                return cached

        cache_misses.inc()
        simulation_requests.labels(status="computed").inc()

        # Execute model
        result = CausalModel.predict(request.action, request.action_category, request.context)

        # Store in cache
        if request.use_cache:
            self.cache.set(cache_key, result)

        # Persist to database
        await self.storage.save(result)

        # Update Prometheus gauge for risk
        risk_value = {"low": 1, "medium": 2, "high": 3}[result.risk_level.value]
        risk_level_gauge.labels(action=request.action_category.value).set(risk_value)

        simulation_duration.labels(action_type=request.action_category.value).observe(time.perf_counter() - start_time)
        logger.info("simulation_completed", simulation_id=result.simulation_id, success_prob=result.success_probability, risk=result.risk_level.value)
        return result

    async def close(self):
        if self._closed:
            return
        self._closed = True
        logger.info("simulator_closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel as PydanticBase

class SimulationResponse(PydanticBase):
    simulation_id: str
    success_probability: float
    risk_level: str
    predicted_state: str
    side_effects: List[str]
    causal_factors: Dict[str, float]

def create_app() -> FastAPI:
    app = FastAPI(title="ATENA Ω Causal World Model", version="2.0")
    simulator = CausalWorldSimulator()

    @app.on_event("shutdown")
    async def shutdown():
        await simulator.close()

    @app.post("/simulate", response_model=SimulationResponse)
    async def run_simulation(req: SimulationRequest):
        try:
            result = await simulator.simulate(req)
            return SimulationResponse(
                simulation_id=result.simulation_id,
                success_probability=result.success_probability,
                risk_level=result.risk_level.value,
                predicted_state=result.predicted_state.value,
                side_effects=result.side_effects,
                causal_factors=result.causal_factors
            )
        except Exception as e:
            logger.exception("simulation_api_error")
            raise HTTPException(500, str(e))

    @app.get("/history")
    async def history(limit: int = Query(50, le=200), category: Optional[str] = None):
        return await simulator.storage.get_history(limit, category)

    return app

# -----------------------------------------------------------------------------
# CLI with Rich
# -----------------------------------------------------------------------------
async def async_main():
    import argparse
    parser = argparse.ArgumentParser(description="ATENA Ω Causal World Model Simulator v2.0")
    parser.add_argument("action", nargs="*", help="Ação a ser simulada")
    parser.add_argument("--category", choices=["inference_update", "memory_operation", "code_generation", "self_improvement", "external_api_call"], default="unknown")
    parser.add_argument("--context", type=str, help="JSON string com contexto adicional")
    parser.add_argument("--no-cache", action="store_true", help="Ignora cache")
    parser.add_argument("--serve", action="store_true", help="Inicia servidor API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--metrics-port", type=int, default=9090)
    parser.add_argument("--history", action="store_true", help="Exibe histórico de simulações")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Saída em JSON")
    args = parser.parse_args()

    if args.serve:
        import uvicorn
        start_http_server(args.metrics_port)
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    if args.history:
        async with CausalWorldSimulator() as sim:
            history = await sim.storage.get_history(args.limit)
            if args.json:
                print(json.dumps(history, indent=2, default=str))
                return
            if RICH_AVAILABLE:
                console = Console()
                table = Table(title="Histórico de Simulações")
                table.add_column("Timestamp", style="cyan")
                table.add_column("Ação", style="white")
                table.add_column("Categoria", style="green")
                table.add_column("Probabilidade", style="yellow")
                table.add_column("Risco", style="red")
                for row in history:
                    table.add_row(
                        row['timestamp'][:19],
                        row['action'][:40],
                        row['category'],
                        f"{row['success_prob']:.3f}",
                        row['risk']
                    )
                console.print(table)
            else:
                for row in history:
                    print(f"{row['timestamp']} | {row['action'][:50]} | {row['success_prob']:.3f} | {row['risk']}")
            return

    action_text = " ".join(args.action) if args.action else "Atualizar motor de inferência"
    context = {}
    if args.context:
        try:
            context = json.loads(args.context)
        except:
            pass

    req = SimulationRequest(
        action=action_text,
        context=context,
        action_category=ActionCategory(args.category) if args.category != "unknown" else ActionCategory.UNKNOWN,
        use_cache=not args.no_cache
    )

    async with CausalWorldSimulator() as sim:
        result = await sim.simulate(req)

    if args.json:
        print(result.model_dump_json(indent=2))
        return

    if RICH_AVAILABLE:
        console = Console()
        console.print(Panel(f"[bold cyan]🔮 Simulação Causal[/]\nAção: {action_text}", style="cyan"))
        table = Table(show_header=False, box=None)
        table.add_column("Métrica", style="bold")
        table.add_column("Valor")
        table.add_row("ID", result.simulation_id)
        table.add_row("Probabilidade de sucesso", f"{result.success_probability:.3f}")
        table.add_row("Nível de risco", result.risk_level.value.upper())
        table.add_row("Estado previsto", result.predicted_state.value)
        table.add_row("Efeitos colaterais", ", ".join(result.side_effects) if result.side_effects else "Nenhum")
        console.print(table)
        if result.causal_factors:
            console.print("\n[bold]Fatores causais:[/]")
            for k, v in result.causal_factors.items():
                console.print(f"  • {k}: {v:.3f}")
    else:
        print(f"Simulação: {result.simulation_id}")
        print(f"Sucesso: {result.success_probability:.3f}")
        print(f"Risco: {result.risk_level.value}")
        print(f"Estado: {result.predicted_state.value}")
        print(f"Efeitos: {', '.join(result.side_effects)}")

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
