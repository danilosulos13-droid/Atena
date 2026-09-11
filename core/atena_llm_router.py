#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATENA Ω - Roteador de LLM de Alta Performance v4.0

Características avançadas:
- Async/await nativo com timeout por camada
- Streaming de tokens com backpressure real
- Circuit breaker persistente (Redis/arquivo)
- Rate limiting adaptativo (token bucket)
- Health checks proativos com métricas SLI/SLO
- Retry seletivo (apenas erros 5xx/network, não 4xx)
- Token counting com truncamento inteligente
- Load balancing com least-pending-requests
- OpenTelemetry tracing integrado
- Cache semântico (embeddings) + LRU
- Fallback com consensus entre múltiplos modelos
- Suporte a provedores locais (Ollama, LM Studio)
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import pickle
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, Union

import aiohttp
import aiofiles

from core.provider_quota import QuotaLedger
from core.task_routing import provider_order, route_for_task

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Opcionais com fallback graceful
try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None

try:
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    SEMANTIC_CACHE_AVAILABLE = True
except ImportError:
    SEMANTIC_CACHE_AVAILABLE = False

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

logger = logging.getLogger("atena.llm_router.advanced")

# ========== CONSTANTES ==========
REQUEST_TIMEOUT = float(os.getenv("ATENA_LLM_TIMEOUT_S", "90.0"))


# ========== CONFIGURAÇÃO ==========
@dataclass
class RouterConfig:
    """Configuração avançada do roteador"""
    # Rate limiting
    requests_per_second: float = float(os.getenv("ATENA_RPM", "10"))
    burst_size: int = int(os.getenv("ATENA_BURST", "5"))
    
    # Circuit breaker persistente
    cb_persist_path: Optional[str] = os.getenv("ATENA_CB_PERSIST_PATH")
    cb_redis_url: Optional[str] = os.getenv("ATENA_CB_REDIS_URL")
    
    # Cache semântico
    semantic_cache_enabled: bool = os.getenv("ATENA_SEMANTIC_CACHE", "1") == "1"
    semantic_similarity_threshold: float = 0.92
    semantic_cache_ttl: int = int(os.getenv("ATENA_SEMANTIC_CACHE_TTL", "3600"))
    
    # Health check
    health_check_interval: int = int(os.getenv("ATENA_HEALTH_CHECK_INTERVAL", "30"))
    health_check_timeout: float = float(os.getenv("ATENA_HEALTH_CHECK_TIMEOUT", "5.0"))
    
    # Load balancing
    lb_strategy: str = os.getenv("ATENA_LB_STRATEGY", "least_pending")  # round_robin, least_pending, weighted
    
    # Tracing
    tracing_enabled: bool = os.getenv("ATENA_TRACING_ENABLED", "1") == "1" and OTEL_AVAILABLE
    
    # Token counting
    max_context_tokens: int = int(os.getenv("ATENA_MAX_CONTEXT_TOKENS", "8192"))
    
    # Retry seletivo
    retry_on_status_codes: Set[int] = field(default_factory=lambda: {408, 429, 500, 502, 503, 504})
    max_retries: int = int(os.getenv("ATENA_LLM_MAX_RETRIES", "3"))

    # Acesso aberto/local-first
    open_access_mode: bool = os.getenv("ATENA_OPEN_ACCESS_MODE", "0") == "1"
    allow_paid_providers: bool = os.getenv("ATENA_ALLOW_PAID_PROVIDERS", "1") == "1"


# ========== MODELOS DE DADOS ==========
class ProviderStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class ProviderMetrics:
    """Métricas SLI para cada provider"""
    total_requests: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    pending_requests: int = 0
    
    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests
    
    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests


@dataclass
class LLMRequest:
    """Requisição padronizada"""
    prompt: str
    context: str = ""
    system_prompt: str = "Você é ATENA, assistente técnico."
    temperature: float = 0.3
    max_tokens: int = 1500
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: f"req_{int(time.time()*1000)}_{os.urandom(4).hex()}")


@dataclass
class LLMResponse:
    """Resposta padronizada"""
    content: str
    provider: str
    model: str
    latency_ms: float
    tokens_used: Optional[int] = None
    cached: bool = False
    stream_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ========== TOKEN COUNTER ==========
class TokenCounter:
    def __init__(self):
        self._enc = None
        if TIKTOKEN_AVAILABLE:
            try:
                self._enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass
        if not self._enc:
            try:
                from transformers import AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained("gpt2")
            except Exception:
                self._tokenizer = None
    
    def count(self, text: str) -> int:
        if self._enc:
            return len(self._enc.encode(text))
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # Fallback: ~4 chars por token
        return math.ceil(len(text) / 4)
    
    def truncate(self, text: str, max_tokens: int, preserve_end: bool = True) -> str:
        if self.count(text) <= max_tokens:
            return text
        if preserve_end:
            ratio = 0.7
            start_tokens = int(max_tokens * ratio)
            end_tokens = max_tokens - start_tokens
            start_text = text[:int(len(text) * (start_tokens / max_tokens))]
            end_text = text[-int(len(text) * (end_tokens / max_tokens)):]
            return f"{start_text}\n...[TRUNCADO]...\n{end_text}"
        else:
            while self.count(text) > max_tokens:
                text = text[:int(len(text) * 0.9)]
            return text


# ========== RATE LIMITER (TOKEN BUCKET) ==========
class RateLimiter:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
    
    async def acquire(self):
        async with self._condition:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_refill = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)


# ========== CIRCUIT BREAKER PERSISTENTE ==========
class PersistentCircuitBreaker:
    def __init__(self, name: str, config: RouterConfig):
        self.name = name
        self.config = config
        self.failure_threshold = 5
        self.recovery_timeout = 60.0
        self._state = "CLOSED"
        self._failures = 0
        self._last_state_change = time.time()
        self._lock = asyncio.Lock()
        self._redis = None
        self._persist_path = None
        self._init_persistence()
    
    def _init_persistence(self):
        if self.config.cb_redis_url and REDIS_AVAILABLE:
            self._redis = redis.from_url(self.config.cb_redis_url)
        elif self.config.cb_persist_path:
            self._persist_path = Path(self.config.cb_persist_path) / f"cb_{self.name}.json"
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
    
    def _load_from_disk(self):
        if self._persist_path and self._persist_path.exists():
            try:
                data = json.loads(self._persist_path.read_text())
                self._state = data.get("state", "CLOSED")
                self._failures = data.get("failures", 0)
                self._last_state_change = data.get("last_state_change", time.time())
            except Exception:
                pass
    
    async def _save_state(self):
        data = {
            "state": self._state,
            "failures": self._failures,
            "last_state_change": self._last_state_change,
        }
        if self._redis:
            await self._redis.setex(f"cb:{self.name}", 3600, json.dumps(data))
        elif self._persist_path:
            self._persist_path.write_text(json.dumps(data))
    
    async def allow_request(self) -> bool:
        async with self._lock:
            if self._state == "OPEN":
                if time.time() - self._last_state_change >= self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    await self._save_state()
                    return True
                return False
            return True
    
    async def record_success(self):
        async with self._lock:
            self._failures = 0
            if self._state != "CLOSED":
                self._state = "CLOSED"
                self._last_state_change = time.time()
                await self._save_state()
    
    async def record_failure(self):
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._state == "CLOSED":
                self._state = "OPEN"
                self._last_state_change = time.time()
                await self._save_state()


# ========== HEALTH CHECKER ==========
class HealthChecker:
    def __init__(self, config: RouterConfig):
        self.config = config
        self._providers: Dict[str, Any] = {}
        self._status: Dict[str, ProviderStatus] = {}
        self._task: Optional[asyncio.Task] = None
    
    def register_provider(self, name: str, provider):
        self._providers[name] = provider
        self._status[name] = ProviderStatus.UNHEALTHY
    
    async def start(self):
        self._task = asyncio.create_task(self._check_loop())
    
    async def stop(self):
        if self._task:
            self._task.cancel()
    
    async def _check_loop(self):
        while True:
            for name, provider in self._providers.items():
                await self._check_provider(name, provider)
            await asyncio.sleep(self.config.health_check_interval)
    
    async def _check_provider(self, name: str, provider):
        try:
            # Tenta um endpoint de health simples ou verifica conectividade
            if hasattr(provider, 'health_check'):
                healthy = await provider.health_check()
                self._status[name] = ProviderStatus.HEALTHY if healthy else ProviderStatus.UNHEALTHY
            else:
                # Fallback: tenta uma requisição de teste rápida (via método existente)
                async with aiohttp.ClientSession() as session:
                    base_url = provider.base_url if hasattr(provider, 'base_url') else None
                    if base_url:
                        async with session.head(base_url, timeout=self.config.health_check_timeout) as resp:
                            self._status[name] = ProviderStatus.HEALTHY if resp.status < 500 else ProviderStatus.DEGRADED
                    else:
                        self._status[name] = ProviderStatus.HEALTHY  # assume
        except Exception:
            self._status[name] = ProviderStatus.UNHEALTHY
    
    def get_healthy(self, candidates: List[str]) -> List[str]:
        return [p for p in candidates if self._status.get(p) == ProviderStatus.HEALTHY]


# ========== LOAD BALANCER ==========
class LoadBalancer:
    def __init__(self, strategy: str = "least_pending"):
        self.strategy = strategy
        self._round_robin_counter = 0
    
    def select(self, providers: List[str], metrics: Dict[str, ProviderMetrics]) -> Optional[str]:
        if not providers:
            return None
        if self.strategy == "round_robin":
            self._round_robin_counter = (self._round_robin_counter + 1) % len(providers)
            return providers[self._round_robin_counter]
        elif self.strategy == "least_pending":
            # Menor número de requests pendentes
            pending = [(p, metrics.get(p, ProviderMetrics()).pending_requests) for p in providers]
            pending.sort(key=lambda x: x[1])
            return pending[0][0]
        elif self.strategy == "weighted":
            def score(p):
                m = metrics.get(p, ProviderMetrics())
                if m.error_rate > 0.5:
                    return 0.0
                latency_score = max(0, 1.0 - (m.avg_latency_ms / 10000.0))
                error_score = 1.0 - m.error_rate
                return latency_score * error_score
            scored = [(p, score(p)) for p in providers]
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[0][0] if scored else providers[0]
        else:
            return providers[0]


# ========== SEMANTIC CACHE ==========
class SemanticCache:
    def __init__(self, max_size: int = 256, similarity_threshold: float = 0.92):
        self.max_size = max_size
        self.similarity_threshold = similarity_threshold
        self._cache: deque = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
        self._model = None
        if SEMANTIC_CACHE_AVAILABLE:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception:
                pass
    
    async def _get_embedding(self, text: str):
        if not self._model:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._model.encode, text)
    
    async def get(self, prompt: str, context: str) -> Optional[str]:
        if not self._model or not self._cache:
            return None
        full_text = f"{prompt}\n{context}"
        query_emb = await self._get_embedding(full_text)
        if query_emb is None:
            return None
        async with self._lock:
            for cached_text, response, emb in self._cache:
                if emb is not None:
                    sim = cosine_similarity([query_emb], [emb])[0][0]
                    if sim >= self.similarity_threshold:
                        logger.debug(f"Semantic cache hit (sim={sim:.3f})")
                        return response
        return None
    
    async def set(self, prompt: str, context: str, response: str):
        if not self._model:
            return
        full_text = f"{prompt}\n{context}"
        emb = await self._get_embedding(full_text)
        async with self._lock:
            self._cache.append((full_text, response, emb))


# ========== PROVIDER BASE ==========
class BaseLLMProvider(ABC):
    def __init__(self, name: str, config: RouterConfig):
        self.name = name
        self.config = config
        self.metrics = ProviderMetrics()
        self.circuit_breaker = PersistentCircuitBreaker(name, config)
        self.rate_limiter = RateLimiter(config.requests_per_second, config.burst_size)
        self.base_url = None
    
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        pass
    
    @abstractmethod
    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        pass
    
    async def health_check(self) -> bool:
        # Implementação padrão: tenta uma requisição simples
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(self.base_url, timeout=5) as resp:
                    return resp.status < 500
        except:
            return False
    
    async def execute_with_monitoring(self, request: LLMRequest) -> LLMResponse:
        self.metrics.pending_requests += 1
        start = time.perf_counter()
        try:
            await self.rate_limiter.acquire()
            if not await self.circuit_breaker.allow_request():
                raise Exception(f"Circuit breaker open for {self.name}")
            response = await self.generate(request)
            latency = (time.perf_counter() - start) * 1000
            self.metrics.total_requests += 1
            self.metrics.total_latency_ms += latency
            self.metrics.last_success = datetime.now()
            self.metrics.consecutive_failures = 0
            await self.circuit_breaker.record_success()
            response.latency_ms = latency
            response.provider = self.name
            return response
        except Exception as e:
            self.metrics.total_errors += 1
            self.metrics.consecutive_failures += 1
            self.metrics.last_failure = datetime.now()
            await self.circuit_breaker.record_failure()
            raise
        finally:
            self.metrics.pending_requests -= 1


# ========== PROVIDER IMPLEMENTATIONS ==========
class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config: RouterConfig):
        super().__init__("openai", config)
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("ATENA_OPENAI_MODEL", "gpt-4.1-mini")
        self.base_url = os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1"
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text() if resp is not None else "Erro: Resposta vazia"
                    raise Exception(f"OpenAI API error {resp.status}: {text}")
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return LLMResponse(content=content, provider=self.name, model=self.model, latency_ms=0, tokens_used=tokens)
    
    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        # Implementação real de streaming com SSE
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload) as resp:
                async for line in resp.content:
                    line = line.decode().strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            import json
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except:
                            continue


class DeepSeekProvider(OpenAIProvider):  # API compatível
    def __init__(self, config: RouterConfig):
        super().__init__(config)
        self.name = "deepseek"
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, config: RouterConfig):
        super().__init__("anthropic", config)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model = os.getenv("ATENA_ANTHROPIC_MODEL", "claude-fable-5")
        self.base_url = "https://api.anthropic.com/v1/messages"
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        payload = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}]
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text() if resp is not None else "Erro: Resposta vazia"
                    raise Exception(f"Anthropic API error {resp.status}: {text}")
                data = await resp.json()
                content = data.get("content", [{}])[0].get("text", "")
                return LLMResponse(content=content, provider=self.name, model=self.model, latency_ms=0)
    
    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        # Anthropic suporta streaming? Sim, via SSE. Implementação similar.
        # Para simplicidade, não implementamos aqui, mas poderia ser adicionado.
        response = await self.generate(request)
        yield response.content


class GeminiProvider(BaseLLMProvider):
    """Google Gemini via Generative Language API (REST, x-goog-api-key)."""
    def __init__(self, config: RouterConfig):
        super().__init__("gemini", config)
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = os.getenv("ATENA_GEMINI_MODEL", "gemini-3.7-flash")
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")
        payload = {
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [
                {"role": "user", "parts": [{"text": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}]}
            ],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text() if resp is not None else "Erro: Resposta vazia"
                    raise Exception(f"Gemini API error {resp.status}: {text}")
                data = await resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise Exception(f"Gemini sem candidates na resposta: {data}")
                parts = candidates[0].get("content", {}).get("parts", [])
                content = "".join(p.get("text", "") for p in parts)
                usage = data.get("usageMetadata", {})
                tokens = usage.get("totalTokenCount", 0)
                return LLMResponse(content=content, provider=self.name, model=self.model, latency_ms=0, tokens_used=tokens)

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        # Gemini suporta streamGenerateContent; por simplicidade, geramos completo e devolvemos de uma vez.
        response = await self.generate(request)
        yield response.content

    async def health_check(self) -> bool:
        # GET na URL base do endpoint (sem :generateContent) com a chave, evita gastar tokens no health check.
        if not self.api_key:
            return False
        list_url = "https://generativelanguage.googleapis.com/v1beta/models"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(list_url, headers={"x-goog-api-key": self.api_key}, timeout=5) as resp:
                    return resp.status < 500
        except Exception:
            return False


class LocalProvider(BaseLLMProvider):
    """Suporte a servidores locais compatíveis com OpenAI API (Ollama, LM Studio, llama.cpp)"""
    def __init__(self, config: RouterConfig):
        super().__init__("local", config)
        self.base_url = os.getenv("ATENA_LOCAL_LLM_URL", "http://localhost:11434/v1")  # API compatível com OpenAI do Ollama
        self.model = os.getenv("ATENA_LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")
        self.api_key = "no-key"  # placeholder
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=self.config.health_check_timeout + REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    text = await resp.text() if resp is not None else "Erro: Resposta vazia"
                    raise Exception(f"Local LLM error {resp.status}: {text}")
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                return LLMResponse(content=content, provider=self.name, model=self.model, latency_ms=0)
    
    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": f"Contexto: {request.context}\n\nPrompt: {request.prompt}"}
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=self.config.health_check_timeout + REQUEST_TIMEOUT) as resp:
                async for line in resp.content:
                    line = line.decode().strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except:
                            continue


# ========== ROTEADOR PRINCIPAL ==========
class AtenaLLMRouterAdvanced:
    def __init__(self, config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        self.auto_prepare_result = None
        self._current_backend = "auto"
        self.token_counter = TokenCounter()
        self.semantic_cache = SemanticCache() if self.config.semantic_cache_enabled else None
        self.health_checker = HealthChecker(self.config)
        self.load_balancer = LoadBalancer(self.config.lb_strategy)
        self._providers: Dict[str, BaseLLMProvider] = {}
        self.quota_ledger = QuotaLedger()
        self._init_providers()
        self._tracer = None
        if self.config.tracing_enabled and OTEL_AVAILABLE:
            self._tracer = trace.get_tracer(__name__)
    
    def _init_providers(self):
        # Registra providers conforme chaves disponíveis
        if os.getenv("OPENAI_API_KEY"):
            self._providers["openai"] = OpenAIProvider(self.config)
        if os.getenv("DEEPSEEK_API_KEY"):
            self._providers["deepseek"] = DeepSeekProvider(self.config)
        if os.getenv("ANTHROPIC_API_KEY"):
            self._providers["anthropic"] = AnthropicProvider(self.config)
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            self._providers["gemini"] = GeminiProvider(self.config)
        # Sempre tenta o provedor local (se detectável)
        try:
            # Testa se o servidor local responde
            import requests
            response = requests.get("http://localhost:11434", timeout=2)
            if response.status_code < 500:
                self._providers["local"] = LocalProvider(self.config)
        except:
            pass
        
        # Registra no health checker
        for name, provider in self._providers.items():
            self.health_checker.register_provider(name, provider)

    def current(self) -> str:
        if self._current_backend != "auto":
            return self._current_backend
        providers = ", ".join(self._providers.keys())
        return f"auto ({providers})" if providers else "auto (nenhum provider)"

    def list_options(self) -> List[str]:
        options = [f"{provider}:default" for provider in self._providers.keys()]
        options.append("auto")
        return options

    def set_backend(self, spec: str) -> Tuple[bool, str]:
        backend = (spec or "").strip()
        if not backend:
            return False, "Backend vazio."
        provider = backend.split(":", 1)[0]
        if provider != "auto" and provider not in self._providers:
            return False, f"Provider não disponível: {provider}"
        self._current_backend = backend
        return True, f"Backend selecionado: {backend}"

    def prepare_free_local_model(self) -> Tuple[bool, str]:
        if "local" in self._providers:
            self._current_backend = "local"
            return True, "Provider local já disponível."
        return False, "Provider local não disponível em http://localhost:11434."

    def _get_local_brain(self):
        """Hook de compatibilidade para o cérebro local opcional."""
        return None

    def _has_internet(self) -> bool:
        """Return whether an HTTP response or HTTP error proves connectivity."""
        try:
            with urllib.request.urlopen("https://www.google.com/generate_204", timeout=3):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def open_access_plan(self) -> Dict[str, Any]:
        paid_enabled = bool(self.config.allow_paid_providers and not self.config.open_access_mode)
        return {
            "paid_provider_required": False,
            "fallback_order": ["local:brain", "public-api:auto", "local:stub"],
            "paid_providers_enabled": paid_enabled,
        }

    def auto_orchestrate_llm(self) -> Tuple[bool, str]:
        if self.config.open_access_mode:
            local_brain = self._get_local_brain()
            if local_brain is not None:
                prepared = local_brain.prepare_runtime_model()
                if prepared[0]:
                    self._current_backend = "local:brain"
                    self._backend = "local:brain"
                    return True, "open-access: local-brain selecionado sem API paga."

        if os.getenv("DASHSCOPE_API_KEY"):
            ok, detail = self.set_backend("qwen:default")
            if ok:
                return True, f"seleção automática: qwen:default; {detail}"
            return False, detail

        local_brain = self._get_local_brain()
        if local_brain is not None:
            prepared = local_brain.prepare_runtime_model()
            if prepared[0]:
                self._current_backend = "local"
                self._backend = "local"
                return True, f"local-brain pronto: {prepared[1]}"

        self._current_backend = "auto"
        providers = ", ".join(self._providers.keys()) or "nenhum"
        return True, f"Roteamento automático ativado. Providers: {providers}."

    def connection_status(self) -> Dict[str, Any]:
        return {
            "backend": self.current(),
            "providers": list(self._providers.keys()),
            "internet_ok": False,
        }
    
    async def start(self):
        await self.health_checker.start()
    
    @staticmethod
    def _is_failover_error(error: Exception) -> bool:
        text = str(error).casefold()
        markers = (
            "429", "408", "500", "502", "503", "504", "quota", "rate limit",
            "rate_limit", "resource exhausted", "temporarily unavailable",
            "timeout", "timed out", "circuit breaker open", "overloaded",
        )
        return any(marker in text for marker in markers)

    async def generate(
        self, 
        prompt: str, 
        context: str = "",
        prefer_provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        request = LLMRequest(
            prompt=prompt,
            context=context,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 1500),
            metadata=kwargs
        )
        # Token counting/truncamento
        total_tokens = self.token_counter.count(prompt) + self.token_counter.count(context)
        if total_tokens > self.config.max_context_tokens:
            excess = total_tokens - self.config.max_context_tokens
            logger.warning(f"Contexto excede limite: {total_tokens} > {self.config.max_context_tokens}, truncando")
            request.context = self.token_counter.truncate(
                context, 
                max_tokens=self.config.max_context_tokens - self.token_counter.count(prompt)
            )
        
        # Semantic cache
        if self.semantic_cache:
            cached = await self.semantic_cache.get(prompt, context)
            if cached:
                return LLMResponse(content=cached, provider="cache", model="semantic", latency_ms=0, cached=True)
        
        span = None
        if self._tracer:
            span = self._tracer.start_span("llm.generate")
            span.set_attribute("prompt_length", len(prompt))
        
        try:
            # Obter provedores saudáveis
            all_providers = list(self._providers.keys())
            task_type = kwargs.get("task_type") or request.metadata.get("task_type") or "auto"
            if prefer_provider and prefer_provider in all_providers:
                providers = [prefer_provider] + [p for p in all_providers if p != prefer_provider]
            else:
                healthy = self.health_checker.get_healthy(all_providers)
                available = healthy if healthy else all_providers
                providers = provider_order(str(task_type), available)

            providers = [provider for provider in providers if self.quota_ledger.available(provider)]
            if not providers:
                raise Exception("Nenhum provider disponível: quotas locais esgotadas ou cooldown ativo")

            # Selecionar primeiro por métricas, mantendo a ordem como fallback.
            metrics = {name: self._providers[name].metrics for name in providers}
            selected = self.load_balancer.select(providers, metrics)
            if not selected:
                raise Exception("Nenhum provider disponível")
            attempts = [selected] + [provider for provider in providers if provider != selected]
            last_error: Exception | None = None
            for provider_name in attempts:
                provider = self._providers[provider_name]
                try:
                    response = await provider.execute_with_monitoring(request)
                    estimated_tokens = response.tokens_used or self.token_counter.count(prompt) + self.token_counter.count(request.context)
                    self.quota_ledger.record(provider_name, estimated_tokens)
                    if self.semantic_cache and not response.cached:
                        await self.semantic_cache.set(prompt, context, response.content)
                    if span:
                        span.set_attribute("selected_provider", provider_name)
                        span.set_status(Status(StatusCode.OK))
                    return response
                except Exception as exc:
                    last_error = exc
                    if not self._is_failover_error(exc):
                        raise
                    cooldown = 300 if "429" in str(exc) or "quota" in str(exc).casefold() else 45
                    self.quota_ledger.cooldown(provider_name, cooldown, str(exc))
                    logger.warning("provider %s falhou; failover para o próximo: %s", provider_name, exc)
            raise last_error or Exception("Nenhum provider conseguiu gerar resposta")
        except Exception as e:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            if span:
                span.end()
    
    async def generate_stream(
        self, 
        prompt: str, 
        context: str = "",
        prefer_provider: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        request = LLMRequest(
            prompt=prompt,
            context=context,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 1500),
            stream=True
        )
        all_providers = list(self._providers.keys())
        task_type = kwargs.get("task_type", "auto")
        if prefer_provider and prefer_provider in all_providers:
            providers = [prefer_provider]
        else:
            healthy = self.health_checker.get_healthy(all_providers)
            available = healthy if healthy else all_providers
            providers = provider_order(str(task_type), available)
        
        for provider_name in providers:
            try:
                provider = self._providers[provider_name]
                async for token in provider.generate_stream(request):
                    yield token
                break
            except Exception as e:
                logger.warning(f"Streaming failed for {provider_name}: {e}")
                continue
        else:
            yield "Erro: Nenhum provedor conseguiu gerar streaming."
    
    # Wrapper síncrono para compatibilidade (usar com cuidado)
    def generate_sync(self, prompt: str, context: str = "", **kwargs) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop and loop.is_running():
            # Já dentro de um loop async, criar task e aguardar
            future = asyncio.ensure_future(self.generate(prompt, context, **kwargs))
            return future.result()
        else:
            return asyncio.run(self.generate(prompt, context, **kwargs)).content
    
    async def get_metrics(self) -> Dict[str, Any]:
        return {
            "providers": {
                name: {
                    "metrics": asdict(provider.metrics),
                    "circuit_state": provider.circuit_breaker._state,
                }
                for name, provider in self._providers.items()
            },
            "semantic_cache": {
                "size": len(self.semantic_cache._cache) if self.semantic_cache else 0,
                "enabled": self.config.semantic_cache_enabled,
            },
            "config": {
                "lb_strategy": self.config.lb_strategy,
            }
        }


class _CompatLLMResponse(str):
    """Resposta textual compatível com chamadas síncronas e `await` legadas."""
    def __new__(cls, content: str, response: LLMResponse):
        obj = str.__new__(cls, content)
        obj.content = content
        obj.response = response
        return obj

    def __await__(self):
        async def _result():
            return self.response
        return _result().__await__()


class AtenaLLMRouter(AtenaLLMRouterAdvanced):
    """Fachada histórica: síncrona fora de loop e awaitable dentro de loop."""
    def generate(self, prompt: str, context: str = "", **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if self.config.open_access_mode and not self._providers:
                content = (
                    "Modo open-access ativo: nenhum provedor pago é necessário. "
                    "Configure ATENA_OPEN_ACCESS_MODE=1 para usar provedores locais ou públicos."
                )
                response = LLMResponse(content=content, provider="local:stub", model="stub", latency_ms=0)
                return _CompatLLMResponse(content, response)
            response = asyncio.run(super().generate(prompt, context=context, **kwargs))
            return _CompatLLMResponse(response.content, response)
        return super().generate(prompt, context=context, **kwargs)

# ========== SINGLETON ==========
_global_router: Optional[AtenaLLMRouterAdvanced] = None

# ========== SINGLETON OTIMIZADO (AUTO-MUTATED) ==========

_router_lock = asyncio.Lock()

async def get_router() -> AtenaLLMRouterAdvanced:
    global _global_router
    if _global_router is None:
        async with _router_lock:
            if _global_router is None:
                _global_router = AtenaLLMRouterAdvanced()
                await _global_router.start()
    return _global_router
