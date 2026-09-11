#!/usr/bin/env python3
"""
scan_github_ai_repos.py — Scanner de repositórios de IA para absorção pela ATENA

Melhorias em relação à versão original:
  ✦ Paginação real (até MAX_PAGES por query)
  ✦ Rate-limit awareness — lê X-RateLimit-* e dorme quando necessário
  ✦ Retry com backoff exponencial em falhas transitórias
  ✦ Fetch paralelo com ThreadPoolExecutor
  ✦ Scoring composto: popularidade + velocidade + saúde + frescor + relevância
  ✦ Velocidade de crescimento (stars/dia desde criação)
  ✦ Delta tracking — detecta "foguetes" comparando com watchlist anterior
  ✦ README mining — extrai tech stack, arxiv links, badges CI/coverage
  ✦ Contribuidores únicos (proxy de saúde comunitária)
  ✦ Cadência de releases — última tag via /releases/latest
  ✦ Cross-reference PyPI e HuggingFace para verificar adoção real
  ✦ Tech stack fingerprinting — frameworks e ferramentas detectados
  ✦ Padrões de absorção expandidos com 14 categorias
  ✦ Relatório rich em terminal + Markdown + JSON
  ✦ Hooks de integração com KnowledgeBase da ATENA
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("atena.github_scan")

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_PATH        = ROOT / "docs" / "ai_repo_watchlist.json"
ABSORPTION_REPORT_DIR = ROOT / "analysis_reports"
ABSORPTION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
DELTA_CACHE_PATH      = ROOT / "docs" / "watchlist_prev.json"

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

API_URL = "https://api.github.com/search/repositories"
README_URL = "https://api.github.com/repos/{full_name}/readme"
RELEASES_URL = "https://api.github.com/repos/{full_name}/releases/latest"
CONTRIBUTORS_URL = "https://api.github.com/repos/{full_name}/contributors?per_page=1&anon=1"

MAX_PAGES          = int(os.getenv("ATENA_SCAN_MAX_PAGES", "3"))
PER_PAGE           = 30
MAX_WORKERS        = int(os.getenv("ATENA_SCAN_WORKERS", "6"))
TOP_N              = int(os.getenv("ATENA_SCAN_TOP_N", "80"))
README_TOP_N       = int(os.getenv("ATENA_SCAN_README_N", "15"))   # repos para minerar README
ENRICH_TOP_N       = int(os.getenv("ATENA_SCAN_ENRICH_N", "30"))   # repos para buscar contributors/releases
RETRY_MAX          = 4
RETRY_BASE_SLEEP   = 1.5
REQUEST_TIMEOUT    = 20

# ---------------------------------------------------------------------------
# Queries — cobertura máxima de IA/ML/agentes
# ---------------------------------------------------------------------------

DEFAULT_QUERIES: List[str] = [
    # Agentes autônomos
    "topic:ai-agent stars:>500 archived:false",
    "autonomous ai agent framework stars:>300 archived:false",
    "multi-agent orchestration llm stars:>200 archived:false",
    "agentic workflow automation stars:>200 archived:false",
    # LLM / modelos
    "topic:large-language-models stars:>1000 archived:false",
    "topic:llm stars:>800 archived:false",
    '"llm" inference serving stars:>500 archived:false',
    "local llm inference stars:>300 archived:false",
    # RAG / memória
    "topic:rag retrieval augmented generation stars:>400 archived:false",
    "vector database embeddings ai stars:>500 archived:false",
    # Frameworks IA
    "topic:artificial-intelligence stars:>5000 archived:false",
    "topic:machine-learning stars:>5000 archived:false",
    "topic:deep-learning stars:>3000 archived:false",
    "ai framework python stars:>2000 archived:false",
    # Auto-melhoria / evolução
    "self improving ai code generation stars:>100 archived:false",
    "neural architecture search stars:>200 archived:false",
    "evolutionary algorithm optimization python stars:>200 archived:false",
    # Código / ferramentas dev IA
    "ai coding assistant open source stars:>500 archived:false",
    "llm code review automation stars:>200 archived:false",
    "ai test generation stars:>100 archived:false",
    # Benchmarks / evals
    "llm benchmark evaluation open source stars:>200 archived:false",
    "ai safety alignment research stars:>300 archived:false",
    # Computer vision / multimodal
    "topic:computer-vision stars:>2000 archived:false language:python",
    "multimodal vision language model stars:>500 archived:false",
    # NLP
    "topic:natural-language-processing stars:>2000 archived:false",
    "text generation inference stars:>500 archived:false",
    # Reinforcement learning
    "reinforcement learning from human feedback stars:>200 archived:false",
    "topic:reinforcement-learning stars:>1000 archived:false",
    # Infraestrutura IA
    "mlops machine learning pipeline stars:>500 archived:false",
    "model serving deployment ai stars:>400 archived:false",
    # Segurança IA
    "llm red teaming jailbreak stars:>100 archived:false",
    "ai guardrails content moderation stars:>100 archived:false",
    # Brasil / PT
    "inteligencia artificial agente autonomo language:python stars:>50",
]

# ---------------------------------------------------------------------------
# Tech stack — fingerprinting por tópicos e README
# ---------------------------------------------------------------------------

TECH_FINGERPRINTS: Dict[str, List[str]] = {
    "pytorch":       ["pytorch", "torch", "lightning"],
    "tensorflow":    ["tensorflow", "keras", "tf"],
    "jax":           ["jax", "flax", "optax"],
    "langchain":     ["langchain", "langsmith"],
    "llamaindex":    ["llamaindex", "llama-index", "llama_index"],
    "huggingface":   ["transformers", "huggingface", "hf", "diffusers"],
    "openai":        ["openai", "gpt-4", "gpt-3", "chatgpt"],
    "anthropic":     ["anthropic", "claude"],
    "ollama":        ["ollama", "local llm"],
    "vllm":          ["vllm", "vllm"],
    "ray":           ["ray", "ray serve"],
    "fastapi":       ["fastapi", "uvicorn"],
    "docker":        ["docker", "kubernetes", "k8s"],
    "redis":         ["redis", "celery"],
    "postgres":      ["postgresql", "postgres", "pg"],
    "chromadb":      ["chromadb", "chroma"],
    "qdrant":        ["qdrant"],
    "weaviate":      ["weaviate"],
    "pinecone":      ["pinecone"],
    "faiss":         ["faiss"],
    "dspy":          ["dspy"],
    "autogen":       ["autogen", "autogpt"],
    "crewai":        ["crewai", "crew ai"],
    "langgraph":     ["langgraph"],
    "pydantic":      ["pydantic"],
    "gradio":        ["gradio"],
    "streamlit":     ["streamlit"],
}

# ---------------------------------------------------------------------------
# Padrões de absorção — 14 categorias
# ---------------------------------------------------------------------------

ABSORPTION_PATTERNS_MAP: Dict[str, Dict[str, Any]] = {
    "multi_llm_routing": {
        "keywords": ["router", "routing", "multi-llm", "fallback", "provider", "litellm"],
        "pattern": "Roteamento multi-LLM com fallback automático entre provedores.",
        "priority": "ALTA",
    },
    "agent_orchestration": {
        "keywords": ["orchestration", "crew", "swarm", "multi-agent", "workflow", "dag", "pipeline"],
        "pattern": "Orquestração de agentes com DAG de tarefas e comunicação inter-agente.",
        "priority": "ALTA",
    },
    "rag_memory": {
        "keywords": ["rag", "retrieval", "vector", "embedding", "memory", "knowledge base", "index"],
        "pattern": "RAG com indexação vetorial, reranking e memória persistente por sessão.",
        "priority": "ALTA",
    },
    "code_generation": {
        "keywords": ["coding", "code generation", "copilot", "autocomplete", "refactor", "ast"],
        "pattern": "Geração e refatoração de código com validação por AST e testes automáticos.",
        "priority": "ALTA",
    },
    "self_improvement": {
        "keywords": ["self-improving", "evolution", "adaptive", "rlhf", "self-play", "nas", "genetic"],
        "pattern": "Auto-melhoria com feedback loop evolutivo e seleção baseada em fitness.",
        "priority": "MÁXIMA",
    },
    "tool_use": {
        "keywords": ["tool", "function calling", "browser", "computer use", "plugin", "action"],
        "pattern": "Uso de ferramentas externas: navegador, APIs, terminal, sistema de arquivos.",
        "priority": "ALTA",
    },
    "safety_guardrails": {
        "keywords": ["safety", "guardrail", "alignment", "red team", "policy", "filter", "moderation"],
        "pattern": "Guardrails e filtros de segurança com detecção de jailbreak e PII.",
        "priority": "MÉDIA",
    },
    "observability": {
        "keywords": ["observability", "tracing", "monitoring", "logging", "metrics", "langsmith", "helicone"],
        "pattern": "Observabilidade end-to-end: traces, métricas de latência, custo e qualidade.",
        "priority": "MÉDIA",
    },
    "inference_optimization": {
        "keywords": ["quantization", "vllm", "llama.cpp", "gguf", "ggml", "triton", "trt", "inference"],
        "pattern": "Otimização de inferência: quantização, batching, serving de alta throughput.",
        "priority": "MÉDIA",
    },
    "benchmark_eval": {
        "keywords": ["benchmark", "eval", "evaluation", "leaderboard", "mmlu", "humaneval", "lm-eval"],
        "pattern": "Framework de avaliação com benchmarks padronizados e leaderboards automáticos.",
        "priority": "MÉDIA",
    },
    "multimodal": {
        "keywords": ["vision", "multimodal", "image", "video", "audio", "speech", "vlm", "clip"],
        "pattern": "Processamento multimodal: visão, áudio e texto num pipeline unificado.",
        "priority": "BAIXA",
    },
    "federated_distributed": {
        "keywords": ["federated", "distributed", "decentralized", "p2p", "consensus", "shard"],
        "pattern": "Treinamento e inferência federados/distribuídos com coordenação descentralizada.",
        "priority": "BAIXA",
    },
    "data_pipeline": {
        "keywords": ["dataset", "synthetic data", "data augmentation", "crawl", "scrape", "etl"],
        "pattern": "Pipeline de dados: coleta, limpeza, augmentação e geração sintética.",
        "priority": "BAIXA",
    },
    "education_docs": {
        "keywords": ["course", "tutorial", "notebook", "beginner", "roadmap", "awesome", "from scratch"],
        "pattern": "Recursos educacionais de referência: notebooks, tutoriais, roadmaps.",
        "priority": "INFORMACIONAL",
    },
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RepoSnapshot:
    full_name: str
    html_url: str
    description: str
    stars: int
    forks: int
    watchers: int
    open_issues: int
    language: Optional[str]
    topics: List[str]
    license_spdx: Optional[str]
    created_at: str
    updated_at: str
    pushed_at: str
    size_kb: int = 0

    # Enriquecimento (fetch opcional)
    contributors_count: Optional[int] = None
    latest_release: Optional[str] = None    # tag name
    latest_release_date: Optional[str] = None
    readme_excerpt: Optional[str] = None
    arxiv_links: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    ci_badges: List[str] = field(default_factory=list)

    # Scores calculados
    popularity_score: float = 0.0
    velocity_score: float = 0.0   # stars/dia
    freshness_score: float = 0.0
    health_score: float = 0.0
    relevance_score: float = 0.0
    total_score: float = 0.0

    # Contexto delta
    prev_stars: Optional[int] = None        # watchlist anterior
    star_delta: Optional[int] = None
    is_rocket: bool = False                 # crescimento explosivo

    # Temas/padrões
    themes: List[str] = field(default_factory=list)
    absorption_patterns: List[str] = field(default_factory=list)

    def days_since_created(self) -> float:
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            return max(1.0, (datetime.now(timezone.utc) - created).days)
        except Exception:
            return 365.0

    def days_since_pushed(self) -> float:
        try:
            pushed = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - pushed).days
        except Exception:
            return 999.0

    def stars_per_day(self) -> float:
        return round(self.stars / self.days_since_created(), 2)

    def compute_scores(self, max_stars: int = 1) -> None:
        """Scoring composto em 5 dimensões."""
        # 1. Popularidade — log-normalizado para evitar dominância de repos virais
        self.popularity_score = min(1.0, math.log1p(self.stars) / math.log1p(max(max_stars, 1)))

        # 2. Velocidade — stars/dia vs mediana esperada (1 star/dia = baseline)
        spd = self.stars_per_day()
        self.velocity_score = min(1.0, math.log1p(spd) / math.log1p(20))  # 20 stars/dia = top

        # 3. Frescor — penaliza repos sem push há muito tempo
        days_stale = self.days_since_pushed()
        self.freshness_score = max(0.0, 1.0 - (days_stale / 365))

        # 4. Saúde — forks/stars ratio, issues, license, topics
        fork_ratio = min(1.0, self.forks / max(self.stars, 1))
        issue_penalty = min(0.3, self.open_issues / max(self.stars, 1))
        has_license = 0.15 if self.license_spdx and self.license_spdx != "NOASSERTION" else 0
        has_topics = 0.15 if len(self.topics) >= 3 else (0.07 if self.topics else 0)
        has_description = 0.1 if len(self.description) > 60 else 0
        self.health_score = min(1.0, fork_ratio * 0.4 + has_license + has_topics
                                + has_description + (1 - issue_penalty) * 0.2)

        # 5. Relevância — matching de keywords IA
        ai_keywords = {
            "agent", "autonomous", "llm", "gpt", "claude", "gemini", "transformer",
            "rag", "embedding", "vector", "rlhf", "fine-tun", "inference",
            "neural", "evolution", "self-improv", "multimodal", "benchmark",
        }
        text = f"{self.description} {' '.join(self.topics)}".lower()
        matches = sum(1 for kw in ai_keywords if kw in text)
        self.relevance_score = min(1.0, matches / 5)

        # Total ponderado
        self.total_score = round(
            self.popularity_score * 0.30
            + self.velocity_score  * 0.25
            + self.freshness_score * 0.20
            + self.health_score    * 0.15
            + self.relevance_score * 0.10,
            4,
        )

    def compute_themes(self) -> None:
        text = (
            f"{self.full_name} {self.description} "
            f"{' '.join(self.topics)} "
            f"{self.readme_excerpt or ''}"
        ).lower()

        # Tech stack
        found_tech: List[str] = []
        for tech, signals in TECH_FINGERPRINTS.items():
            if any(s in text for s in signals):
                found_tech.append(tech)
        self.tech_stack = found_tech

        # Absorption patterns
        matched_patterns: List[str] = []
        for pat_id, meta in ABSORPTION_PATTERNS_MAP.items():
            if any(kw in text for kw in meta["keywords"]):
                matched_patterns.append(pat_id)
        self.absorption_patterns = matched_patterns

        # Themes (legado — compatível com GitHubEvolutionScanner)
        legacy_themes: List[str] = []
        if self.stars >= 10_000:
            legacy_themes.append("highly_adopted")
        elif self.stars >= 2_000:
            legacy_themes.append("popular")
        if self.days_since_pushed() < 30:
            legacy_themes.append("very_active")
        elif self.days_since_pushed() < 120:
            legacy_themes.append("active")
        if self.is_rocket:
            legacy_themes.append("rocket")
        legacy_themes.extend(self.absorption_patterns[:3])
        self.themes = legacy_themes

    def to_dict(self) -> Dict:
        return {
            "full_name": self.full_name,
            "html_url": self.html_url,
            "description": self.description[:500],
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "language": self.language,
            "topics": self.topics[:15],
            "license": self.license_spdx,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
            "stars_per_day": self.stars_per_day(),
            "contributors_count": self.contributors_count,
            "latest_release": self.latest_release,
            "latest_release_date": self.latest_release_date,
            "readme_excerpt": (self.readme_excerpt or "")[:600],
            "arxiv_links": self.arxiv_links[:5],
            "tech_stack": self.tech_stack,
            "ci_badges": self.ci_badges[:5],
            "scores": {
                "popularity": self.popularity_score,
                "velocity": self.velocity_score,
                "freshness": self.freshness_score,
                "health": self.health_score,
                "relevance": self.relevance_score,
                "total": self.total_score,
            },
            "themes": self.themes,
            "absorption_patterns": self.absorption_patterns,
            "prev_stars": self.prev_stars,
            "star_delta": self.star_delta,
            "is_rocket": self.is_rocket,
        }


# ---------------------------------------------------------------------------
# GitHub API client — rate-limit-aware, retry, paginação
# ---------------------------------------------------------------------------

_rate_lock = threading.Lock()
_rate_remaining = 60
_rate_reset_ts  = 0.0


def _github_request(url: str, *, accept: str = "application/vnd.github+json") -> Any:
    """GET com retry exponencial e resposta ao rate limit."""
    global _rate_remaining, _rate_reset_ts
    headers = {
        "Accept": accept,
        "User-Agent": "atena-ai-repo-scanner/2.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(RETRY_MAX):
        # Aguarda se rate limit esgotado
        with _rate_lock:
            if _rate_remaining <= 2:
                sleep_for = max(0, _rate_reset_ts - time.time()) + 2
                if sleep_for > 0:
                    log.warning(f"Rate limit — aguardando {sleep_for:.0f}s")
                    time.sleep(sleep_for)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                # Atualiza rate-limit tracking
                with _rate_lock:
                    _rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", "60"))
                    _rate_reset_ts  = float(resp.headers.get("X-RateLimit-Reset", "0"))
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # Rate limit secundário
                retry_after = int(exc.headers.get("Retry-After", "30"))
                log.warning(f"429/403 — dormindo {retry_after}s (tentativa {attempt+1})")
                time.sleep(retry_after)
            elif exc.code == 404:
                return {}
            elif exc.code in (500, 502, 503, 504):
                sleep = RETRY_BASE_SLEEP * (2 ** attempt)
                log.warning(f"HTTP {exc.code} — retry em {sleep:.1f}s")
                time.sleep(sleep)
            else:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            sleep = RETRY_BASE_SLEEP * (2 ** attempt)
            log.warning(f"Rede: {exc} — retry em {sleep:.1f}s")
            time.sleep(sleep)

    raise RuntimeError(f"Falha após {RETRY_MAX} tentativas: {url}")


def _iter_pages(query: str, per_page: int = PER_PAGE) -> Iterator[List[Dict]]:
    """Itera páginas de resultados da Search API."""
    for page in range(1, MAX_PAGES + 1):
        params = urllib.parse.urlencode({
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": str(per_page),
            "page": str(page),
        })
        try:
            payload = _github_request(f"{API_URL}?{params}")
        except Exception as exc:
            log.warning(f"Falha na página {page} de '{query[:40]}': {exc}")
            break
        items = payload.get("items", [])
        if not items:
            break
        yield items
        total = payload.get("total_count", 0)
        fetched_so_far = page * per_page
        if fetched_so_far >= total:
            break
        time.sleep(0.3)   # pausa gentil entre páginas


# ---------------------------------------------------------------------------
# Parsers de enriquecimento
# ---------------------------------------------------------------------------

def _parse_readme(full_name: str) -> Tuple[str, List[str], List[str]]:
    """
    Retorna (excerpt, arxiv_links, ci_badges) do README.
    Faz o decode do base64 retornado pela API.
    """
    import base64
    try:
        data = _github_request(README_URL.format(full_name=full_name))
        content_b64 = data.get("content", "")
        if not content_b64:
            return "", [], []
        raw = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")

        # Excerpt — primeiros 800 chars de texto real
        clean = re.sub(r"!\[.*?\]\(.*?\)", "", raw)          # remove imagens
        clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)  # links → texto
        clean = re.sub(r"```[\s\S]*?```", "", clean)          # remove code blocks
        clean = re.sub(r"#{1,6}\s+", "", clean)               # remove headers
        clean = re.sub(r"\s+", " ", clean).strip()
        excerpt = clean[:800]

        # arXiv links
        arxiv = re.findall(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", raw)
        arxiv = list(dict.fromkeys(f"https://arxiv.org/abs/{a}" for a in arxiv))

        # CI/coverage badges
        badges: List[str] = []
        if "github.com/actions" in raw or "github/workflow/status" in raw:
            badges.append("github-actions")
        if "codecov.io" in raw:
            badges.append("codecov")
        if "coveralls.io" in raw:
            badges.append("coveralls")
        if "travis-ci" in raw:
            badges.append("travis")
        if "circleci" in raw:
            badges.append("circleci")
        if "sonarcloud" in raw or "sonarqube" in raw:
            badges.append("sonar")

        return excerpt, arxiv, badges
    except Exception:
        return "", [], []


def _fetch_release(full_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Retorna (tag, published_at) da última release."""
    try:
        data = _github_request(RELEASES_URL.format(full_name=full_name))
        return data.get("tag_name"), data.get("published_at")
    except Exception:
        return None, None


def _fetch_contributors_count(full_name: str) -> Optional[int]:
    """
    Estima número de contribuidores via header Link da API.
    Busca a última página e pega o número da página × per_page.
    """
    try:
        url = CONTRIBUTORS_URL.format(full_name=full_name)
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "atena-ai-repo-scanner/2.0",
            **( {"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"} if os.getenv("GITHUB_TOKEN") else {} )
        })
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            link_header = resp.headers.get("Link", "")
            # Extrai ?page=N da rel="last"
            m = re.search(r'page=(\d+)[^>]*>;\s*rel="last"', link_header)
            if m:
                return int(m.group(1))   # cada página tem 1 contrib (per_page=1)
            # Se não há header Link, todos cabem na primeira página
            data = json.loads(resp.read().decode("utf-8"))
            return len(data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def _build_snapshot(item: Dict) -> RepoSnapshot:
    """Constrói RepoSnapshot a partir de um item da Search API."""
    lic = item.get("license") or {}
    return RepoSnapshot(
        full_name   = item.get("full_name", ""),
        html_url    = item.get("html_url", ""),
        description = (item.get("description") or "").strip(),
        stars       = int(item.get("stargazers_count", 0)),
        forks       = int(item.get("forks_count", 0)),
        watchers    = int(item.get("watchers_count", 0)),
        open_issues = int(item.get("open_issues_count", 0)),
        language    = item.get("language"),
        topics      = item.get("topics") or [],
        license_spdx= lic.get("spdx_id"),
        created_at  = item.get("created_at", ""),
        updated_at  = item.get("updated_at", ""),
        pushed_at   = item.get("pushed_at", ""),
        size_kb     = int(item.get("size", 0)),
    )


# ---------------------------------------------------------------------------
# Busca paralela de múltiplas queries
# ---------------------------------------------------------------------------

def fetch_all_queries(
    queries: List[str],
    per_page: int = PER_PAGE,
) -> List[RepoSnapshot]:
    """Busca todas as queries em paralelo e retorna lista deduplicada."""
    raw_items: Dict[str, Dict] = {}   # full_name → item mais recente
    lock = threading.Lock()

    def _fetch_query(query: str) -> int:
        count = 0
        for page_items in _iter_pages(query, per_page):
            for item in page_items:
                fn = item.get("full_name", "")
                if not fn:
                    continue
                with lock:
                    prev = raw_items.get(fn)
                    # Mantém o item com mais estrelas (em caso de duplicata entre queries)
                    if prev is None or item.get("stargazers_count", 0) > prev.get("stargazers_count", 0):
                        raw_items[fn] = item
                        count += 1
        return count

    log.info(f"🔍 Iniciando busca paralela — {len(queries)} queries, {MAX_WORKERS} workers")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch_query, q): q for q in queries}
        for f in as_completed(futures):
            q = futures[f]
            try:
                n = f.result()
                log.info(f"  ✓ '{q[:55]}' → {n} novos itens")
            except Exception as exc:
                log.warning(f"  ✗ '{q[:55]}' → {exc}")

    snapshots = [_build_snapshot(item) for item in raw_items.values()]
    log.info(f"📦 Total único coletado: {len(snapshots)} repositórios")
    return snapshots


# ---------------------------------------------------------------------------
# Enriquecimento paralelo (README + releases + contributors)
# ---------------------------------------------------------------------------

def enrich_top_repos(repos: List[RepoSnapshot]) -> None:
    """
    Enriquece os TOP repos com README, releases e contributors.
    Modifica a lista in-place.
    """
    to_enrich_readme = repos[:README_TOP_N]
    to_enrich_meta   = repos[:ENRICH_TOP_N]

    log.info(f"📖 Minerando READMEs dos top {len(to_enrich_readme)} repos...")

    def _enrich_readme(repo: RepoSnapshot) -> None:
        excerpt, arxiv, badges = _parse_readme(repo.full_name)
        repo.readme_excerpt = excerpt
        repo.arxiv_links    = arxiv
        repo.ci_badges      = badges

    def _enrich_meta(repo: RepoSnapshot) -> None:
        tag, pub_date = _fetch_release(repo.full_name)
        repo.latest_release      = tag
        repo.latest_release_date = pub_date
        repo.contributors_count  = _fetch_contributors_count(repo.full_name)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(_enrich_readme, to_enrich_readme))

    log.info(f"📊 Buscando releases/contribuidores dos top {len(to_enrich_meta)}...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(_enrich_meta, to_enrich_meta))


# ---------------------------------------------------------------------------
# Cross-reference PyPI e HuggingFace
# ---------------------------------------------------------------------------

def _check_pypi(package_name: str) -> Optional[Dict]:
    """Verifica se o repo tem pacote PyPI e retorna downloads mensais."""
    try:
        url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name)}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "atena-scanner/2.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        info = data.get("info", {})
        return {
            "version": info.get("version", ""),
            "summary": (info.get("summary") or "")[:150],
        }
    except Exception:
        return None


def _check_huggingface(repo_name: str) -> Optional[Dict]:
    """Verifica se o repo tem modelo/dataset no HuggingFace."""
    try:
        owner = repo_name.split("/")[0]
        url = f"https://huggingface.co/api/models?author={urllib.parse.quote(owner)}&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "atena-scanner/2.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data:
            return {"hf_models": [m.get("modelId", "") for m in data[:3]]}
    except Exception:
        pass
    return None


def cross_reference(repos: List[RepoSnapshot], top_n: int = 20) -> Dict[str, Dict]:
    """Retorna cross-reference dict para os top repos."""
    results: Dict[str, Dict] = {}
    log.info(f"🔗 Cross-referencing top {top_n} repos com PyPI/HuggingFace...")

    def _check(repo: RepoSnapshot) -> None:
        name = repo.full_name.split("/")[-1].lower().replace("_", "-")
        pypi = _check_pypi(name)
        hf   = _check_huggingface(repo.full_name)
        if pypi or hf:
            results[repo.full_name] = {"pypi": pypi, "huggingface": hf}

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_check, repos[:top_n]))

    return results


# ---------------------------------------------------------------------------
# Delta tracking — detecta foguetes
# ---------------------------------------------------------------------------

def load_previous_watchlist() -> Dict[str, int]:
    """Carrega watchlist anterior → {full_name: stars}."""
    if not DELTA_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(DELTA_CACHE_PATH.read_text(encoding="utf-8"))
        return {r["full_name"]: r.get("stars", 0) for r in payload.get("repos", [])}
    except Exception:
        return {}


def apply_delta(repos: List[RepoSnapshot], prev: Dict[str, int]) -> None:
    """Calcula deltas e marca foguetes."""
    for repo in repos:
        if repo.full_name in prev:
            prev_stars = prev[repo.full_name]
            repo.prev_stars  = prev_stars
            repo.star_delta  = repo.stars - prev_stars
            # Foguete: cresceu >20% ou >500 stars desde a última varredura
            if repo.star_delta > 0:
                pct = repo.star_delta / max(prev_stars, 1)
                if pct >= 0.20 or repo.star_delta >= 500:
                    repo.is_rocket = True


# ---------------------------------------------------------------------------
# Scoring e ranking final
# ---------------------------------------------------------------------------

def rank_repos(repos: List[RepoSnapshot], top_n: int = TOP_N) -> List[RepoSnapshot]:
    max_stars = max((r.stars for r in repos), default=1)
    for repo in repos:
        repo.compute_scores(max_stars)
        repo.compute_themes()
    return sorted(repos, key=lambda r: r.total_score, reverse=True)[:top_n]


# ---------------------------------------------------------------------------
# Padrões de absorção — inferência a partir do conjunto
# ---------------------------------------------------------------------------

def infer_absorption_report(repos: List[RepoSnapshot]) -> List[Dict]:
    """
    Retorna lista de padrões absorvíveis detectados no conjunto,
    ordenados por prioridade e número de repos que os exemplificam.
    """
    pattern_repos: Dict[str, List[str]] = {pid: [] for pid in ABSORPTION_PATTERNS_MAP}

    for repo in repos:
        for pid in repo.absorption_patterns:
            if pid in pattern_repos:
                pattern_repos[pid].append(repo.full_name)

    priority_order = {"MÁXIMA": 0, "ALTA": 1, "MÉDIA": 2, "BAIXA": 3, "INFORMACIONAL": 4}
    result = []
    for pid, meta in ABSORPTION_PATTERNS_MAP.items():
        exemplars = pattern_repos[pid]
        if not exemplars:
            continue
        result.append({
            "id": pid,
            "pattern": meta["pattern"],
            "priority": meta["priority"],
            "exemplars": exemplars[:5],
            "count": len(exemplars),
        })

    return sorted(result, key=lambda x: (priority_order.get(x["priority"], 9), -x["count"]))


# ---------------------------------------------------------------------------
# Persistência — watchlist e relatório
# ---------------------------------------------------------------------------

def write_watchlist(
    repos: List[RepoSnapshot],
    *,
    source: str,
    queries: List[str],
    cross_refs: Optional[Dict] = None,
) -> Dict:
    """Salva watchlist JSON e faz backup da anterior."""
    # Backup anterior para delta do próximo run
    if WATCHLIST_PATH.exists():
        import shutil
        shutil.copy(WATCHLIST_PATH, DELTA_CACHE_PATH)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "queries_used": len(queries),
        "count": len(repos),
        "cross_references": cross_refs or {},
        "repos": [r.to_dict() for r in repos],
    }
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def write_absorption_report(
    repos: List[RepoSnapshot],
    patterns: List[Dict],
    cross_refs: Dict,
    *,
    source: str,
    warnings: List[str],
    elapsed_s: float,
) -> Path:
    """Gera relatório Markdown rico."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    path = ABSORPTION_REPORT_DIR / f"ATENA_GITHUB_ABSORPTION_{ts}.md"

    rockets = [r for r in repos if r.is_rocket]
    with_arxiv = [r for r in repos if r.arxiv_links]
    top10 = repos[:10]

    # Distribuição de linguagens
    lang_counts: Dict[str, int] = {}
    for r in repos:
        lang_counts[r.language or "Unknown"] = lang_counts.get(r.language or "Unknown", 0) + 1
    top_langs = sorted(lang_counts.items(), key=lambda x: -x[1])[:8]

    # Tech stack agregado
    stack_counts: Dict[str, int] = {}
    for r in repos:
        for t in r.tech_stack:
            stack_counts[t] = stack_counts.get(t, 0) + 1
    top_stack = sorted(stack_counts.items(), key=lambda x: -x[1])[:12]

    lines: List[str] = [
        "# ATENA — Absorção GitHub AI Repositories",
        "",
        f"**Gerado em:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Fonte:** {source}  ",
        f"**Tempo de execução:** {elapsed_s:.1f}s  ",
        f"**Repositórios analisados:** {len(repos)}  ",
        f"**Foguetes detectados:** {len(rockets)}  ",
        f"**Com links arXiv:** {len(with_arxiv)}  ",
        "",
    ]

    if warnings:
        lines += ["## ⚠️ Avisos", ""]
        lines += [f"- {w}" for w in warnings]
        lines.append("")

    if rockets:
        lines += ["## 🚀 Foguetes (crescimento explosivo desde última varredura)", ""]
        for r in sorted(rockets, key=lambda x: -(x.star_delta or 0))[:8]:
            delta_str = f"+{r.star_delta:,}" if r.star_delta else "novo"
            lines.append(
                f"- [`{r.full_name}`]({r.html_url}) — "
                f"**{r.stars:,}** ⭐ ({delta_str}) — {r.description[:80]}"
            )
        lines.append("")

    lines += ["## 🏆 Top 10 por Score Composto", ""]
    for i, r in enumerate(top10, 1):
        spd = r.stars_per_day()
        extras = []
        if r.contributors_count:
            extras.append(f"{r.contributors_count} contribuidores")
        if r.latest_release:
            extras.append(f"última release: {r.latest_release}")
        if r.arxiv_links:
            extras.append(f"📄 arXiv: {r.arxiv_links[0]}")
        extra_str = " | ".join(extras)

        lines += [
            f"### {i}. `{r.full_name}`",
            f"- **Stars:** {r.stars:,} ({spd} ⭐/dia) | **Forks:** {r.forks:,}",
            f"- **Score:** pop={r.popularity_score:.2f} vel={r.velocity_score:.2f} "
            f"fresh={r.freshness_score:.2f} health={r.health_score:.2f} total=**{r.total_score:.3f}**",
            f"- **Stack:** {', '.join(r.tech_stack[:6]) or 'N/A'}",
            f"- **Padrões:** {', '.join(r.absorption_patterns[:4]) or 'N/A'}",
        ]
        if extra_str:
            lines.append(f"- {extra_str}")
        if r.readme_excerpt:
            excerpt = r.readme_excerpt[:250].replace("\n", " ")
            lines.append(f"- *\"{excerpt}...\"*")
        lines.append(f"- {r.html_url}")
        lines.append("")

    lines += ["## 🧬 Padrões de Absorção Detectados", ""]
    for pat in patterns:
        badge = {"MÁXIMA": "🔴", "ALTA": "🟠", "MÉDIA": "🟡", "BAIXA": "🟢", "INFORMACIONAL": "⚪"}.get(pat["priority"], "")
        lines.append(f"### {badge} [{pat['priority']}] {pat['id']} *(em {pat['count']} repos)*")
        lines.append(f"> {pat['pattern']}")
        lines.append(f"**Exemplos:** {', '.join(f'`{e}`' for e in pat['exemplars'][:3])}")
        lines.append("")

    lines += ["## 📊 Estatísticas", ""]
    lines.append(f"**Linguagens predominantes:** {', '.join(f'{l} ({n})' for l, n in top_langs)}")
    lines.append("")
    lines.append(f"**Tech stack mais detectado:**")
    for tech, count in top_stack[:8]:
        bar = "█" * min(20, count)
        lines.append(f"  - `{tech}`: {bar} {count}")
    lines.append("")

    # Cross-references
    if cross_refs:
        lines += ["## 🔗 Cross-Reference PyPI / HuggingFace", ""]
        for full_name, refs in list(cross_refs.items())[:10]:
            parts = []
            if refs.get("pypi"):
                parts.append(f"PyPI v{refs['pypi'].get('version', '?')}")
            if refs.get("huggingface"):
                hf_models = refs["huggingface"].get("hf_models", [])
                parts.append(f"HF: {', '.join(hf_models[:2])}")
            if parts:
                lines.append(f"- `{full_name}`: {' | '.join(parts)}")
        lines.append("")

    # Todos os repos (tabela compacta)
    lines += ["## 📋 Todos os Repositórios Ranqueados", ""]
    lines.append("| # | Repositório | Stars | ⭐/dia | Score | Stack |")
    lines.append("|---|---|---|---|---|---|")
    for i, r in enumerate(repos, 1):
        stack_short = ", ".join(r.tech_stack[:3]) or "—"
        lines.append(
            f"| {i} | [{r.full_name}]({r.html_url}) | "
            f"{r.stars:,} | {r.stars_per_day()} | {r.total_score:.3f} | {stack_short} |"
        )
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Integração com ATENA KnowledgeBase (opcional)
# ---------------------------------------------------------------------------

def feed_atena_kb(repos: List[RepoSnapshot], patterns: List[Dict]) -> bool:
    """
    Alimenta a KnowledgeBase da ATENA com os insights coletados.
    Retorna True se conseguiu conectar ao KB.
    """
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from main import KnowledgeBase
        kb = KnowledgeBase()
        for repo in repos[:20]:
            kb.store(
                category="github_insight",
                key=repo.full_name,
                value=json.dumps(repo.to_dict()),
            )
        for pat in patterns:
            kb.store(
                category="absorption_pattern",
                key=pat["id"],
                value=json.dumps(pat),
            )
        log.info(f"✅ ATENA KB alimentada com {min(20, len(repos))} repos e {len(patterns)} padrões")
        return True
    except Exception as exc:
        log.debug(f"KB não disponível: {exc}")
        return False


# ---------------------------------------------------------------------------
# Fallback — carrega watchlist local quando API inacessível
# ---------------------------------------------------------------------------

def load_watchlist(path: Path = WATCHLIST_PATH) -> List[RepoSnapshot]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        repos = []
        for item in payload.get("repos", []):
            if not isinstance(item, dict) or not item.get("full_name"):
                continue
            repos.append(RepoSnapshot(
                full_name    = item["full_name"],
                html_url     = item.get("html_url", ""),
                description  = item.get("description", ""),
                stars        = item.get("stars", 0),
                forks        = item.get("forks", 0),
                watchers     = item.get("watchers", 0),
                open_issues  = item.get("open_issues", 0),
                language     = item.get("language"),
                topics       = item.get("topics", []),
                license_spdx = item.get("license"),
                created_at   = item.get("created_at", ""),
                updated_at   = item.get("updated_at", ""),
                pushed_at    = item.get("pushed_at", ""),
                readme_excerpt     = item.get("readme_excerpt"),
                arxiv_links        = item.get("arxiv_links", []),
                tech_stack         = item.get("tech_stack", []),
                ci_badges          = item.get("ci_badges", []),
                contributors_count = item.get("contributors_count"),
                latest_release     = item.get("latest_release"),
                latest_release_date= item.get("latest_release_date"),
            ))
        return repos
    except Exception as exc:
        log.warning(f"Erro ao carregar watchlist local: {exc}")
        return []


# ---------------------------------------------------------------------------
# Progress / terminal output
# ---------------------------------------------------------------------------

def _print_summary(repos: List[RepoSnapshot], patterns: List[Dict]) -> None:
    """Imprime resumo no terminal."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        console = Console()
        console.print("\n[bold cyan]🔱 ATENA — GitHub AI Scan[/bold cyan]\n")

        table = Table(title=f"Top 15 Repositórios (de {len(repos)})", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Repositório", style="bold cyan", min_width=30)
        table.add_column("⭐", justify="right", style="yellow")
        table.add_column("⭐/dia", justify="right", style="green")
        table.add_column("Score", justify="right", style="magenta")
        table.add_column("Stack", style="dim", max_width=25)
        table.add_column("🚀", justify="center", width=3)

        for i, r in enumerate(repos[:15], 1):
            rocket = "🚀" if r.is_rocket else ""
            table.add_row(
                str(i),
                r.full_name,
                f"{r.stars:,}",
                str(r.stars_per_day()),
                f"{r.total_score:.3f}",
                ", ".join(r.tech_stack[:3]) or "—",
                rocket,
            )
        console.print(table)

        console.print("\n[bold]🧬 Padrões de absorção:[/bold]")
        priority_colors = {"MÁXIMA": "red", "ALTA": "yellow", "MÉDIA": "cyan",
                           "BAIXA": "green", "INFORMACIONAL": "dim"}
        for pat in patterns[:8]:
            color = priority_colors.get(pat["priority"], "white")
            console.print(
                f"  [{color}]{pat['priority']:12s}[/{color}] {pat['id']:25s} "
                f"({pat['count']} repos) — {pat['pattern'][:60]}"
            )

    except ImportError:
        # Fallback sem rich
        print(f"\n{'='*70}")
        print(f"ATENA — GitHub AI Scan — Top {min(15, len(repos))} repositórios")
        print(f"{'='*70}")
        for i, r in enumerate(repos[:15], 1):
            rocket = " 🚀" if r.is_rocket else ""
            print(f"{i:2d}. {r.full_name:<40} {r.stars:>7,}⭐  {r.total_score:.3f}{rocket}")
        print(f"\nPadrões detectados: {len(patterns)}")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main(
    queries: Optional[List[str]] = None,
    top_n: int = TOP_N,
    enrich: bool = True,
    feed_kb: bool = True,
    cross_ref: bool = True,
) -> int:
    t_start = time.time()
    queries  = queries or DEFAULT_QUERIES
    warnings: List[str] = []
    source   = "GitHub Search API"

    # 1. Carrega delta anterior
    prev_stars = load_previous_watchlist()
    if prev_stars:
        log.info(f"📈 Delta tracking ativo — {len(prev_stars)} repos na watchlist anterior")

    # 2. Busca multi-query paralela
    all_repos: List[RepoSnapshot] = []
    try:
        all_repos = fetch_all_queries(queries, per_page=PER_PAGE)
    except Exception as exc:
        warning = f"Busca API falhou: {exc}"
        warnings.append(warning)
        log.warning(warning)

    # 3. Fallback local se API falhou
    used_fallback = False
    if not all_repos:
        fallback = load_watchlist()
        if fallback:
            all_repos   = fallback
            source      = "local fallback — docs/ai_repo_watchlist.json"
            used_fallback = True
            log.warning(f"Usando fallback local com {len(fallback)} repositórios")
        else:
            log.error("Nenhum repositório coletado e fallback local ausente.")
            return 1

    # 4. Delta tracking
    apply_delta(all_repos, prev_stars)
    rockets = [r for r in all_repos if r.is_rocket]
    if rockets:
        log.info(f"🚀 {len(rockets)} foguetes detectados!")

    # 5. Scoring e ranking
    ranked = rank_repos(all_repos, top_n=top_n)

    # 6. Enriquecimento (README, releases, contributors)
    if enrich and not used_fallback:
        enrich_top_repos(ranked)
        # Recalcula scores e temas com info do README
        max_s = max((r.stars for r in ranked), default=1)
        for r in ranked:
            r.compute_scores(max_s)
            r.compute_themes()

    # 7. Cross-reference PyPI / HuggingFace
    cross_refs: Dict = {}
    if cross_ref and not used_fallback:
        cross_refs = cross_reference(ranked, top_n=25)

    # 8. Padrões de absorção
    patterns = infer_absorption_report(ranked)

    # 9. Persistência
    if not used_fallback:
        write_watchlist(ranked, source=source, queries=queries, cross_refs=cross_refs)
        log.info(f"✅ Watchlist salva: {WATCHLIST_PATH} ({len(ranked)} repos)")

    elapsed = time.time() - t_start
    report_path = write_absorption_report(
        ranked, patterns, cross_refs,
        source=source, warnings=warnings, elapsed_s=elapsed,
    )
    log.info(f"✅ Relatório salvo: {report_path}")

    # 10. Feed ATENA KB
    if feed_kb:
        feed_atena_kb(ranked, patterns)

    # 11. Terminal summary
    _print_summary(ranked, patterns)

    print(f"\n⏱  Concluído em {elapsed:.1f}s — {len(ranked)} repos ranqueados, "
          f"{len(patterns)} padrões, {len(rockets)} foguetes")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ATENA — GitHub AI Repository Scanner v2")
    parser.add_argument("--top-n", type=int, default=TOP_N, help="Nº de repositórios no ranking final")
    parser.add_argument("--pages", type=int, default=MAX_PAGES, help="Páginas por query")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="Workers paralelos")
    parser.add_argument("--no-enrich", action="store_true", help="Pula README/releases/contributors")
    parser.add_argument("--no-kb", action="store_true", help="Não alimenta KnowledgeBase ATENA")
    parser.add_argument("--no-cross-ref", action="store_true", help="Pula cross-reference PyPI/HF")
    parser.add_argument("--query", action="append", dest="extra_queries",
                        help="Adiciona query extra (pode repetir)")
    args = parser.parse_args()

    MAX_PAGES  = args.pages
    MAX_WORKERS = args.workers

    extra_q = args.extra_queries or []
    final_queries = DEFAULT_QUERIES + extra_q

    raise SystemExit(main(
        queries=final_queries,
        top_n=args.top_n,
        enrich=not args.no_enrich,
        feed_kb=not args.no_kb,
        cross_ref=not args.no_cross_ref,
    ))
