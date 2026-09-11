"""
atena_sources_extended.py — Fontes de dados expandidas para a ATENA

Adiciona 40+ novas fontes organizadas em categorias:
  - IA/ML:        Hugging Face, Papers With Code, Replicate Status
  - Código:       GitLab, Sourcegraph, Libraries.io, PyPI, RubyGems, NuGet
  - Ciência:      NASA, DOAJ, CORE, Europe PMC, bioRxiv, ChemSpider, GBIF
  - Finanças:     ExchangeRate-API, Frankfurter, Alpha Vantage (free), CoinGecko
  - Notícias:     GDELT, Mediastack (free tier), Currents API (free), Wikinews
  - Geo/Mapas:    Nominatim, IP-API, Open Elevation, TimeZoneDB free
  - Saúde:        OpenFDA, RxNorm, ICD-11 free browse, SNOMED partial
  - Educação:     Khan Academy (partial), MIT OCW, Coursera Catalog (public)
  - Cultura:      Wikiart (partial), Open Library, Discogs (public search)
  - Governança:   Data.gov (search), Portal Dados Abertos BR, ProPublica Congress
  - Infraestrutura: Shodan InternetDB (free), crt.sh, URLScan (free)
  - Utilitários:  QR-Server, Text Summarization (free tiers), SerpApi free

Cada fonte tem:
  - fetch() → retorna SourceResult padronizado
  - WEIGHT: float (qualidade estimada 0-1)
  - CATEGORY: str
  - REQUIRES_KEY: bool (se precisa de API key para funcionar)
  - KEYWORDS: List[str] (para roteamento por intenção)
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from functools import lru_cache

logger = logging.getLogger("atena.sources_extended")

# ---------------------------------------------------------------------------
# Resultado padronizado (compatível com internet_challenge.SourceResult)
# ---------------------------------------------------------------------------

@dataclass
class ExtSourceResult:
    source: str
    ok: bool
    details: Dict[str, Any]
    response_time_ms: float = 0.0
    category: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário para serialização"""
        return {
            "source": self.source,
            "ok": self.ok,
            "details": self.details,
            "response_time_ms": self.response_time_ms,
            "category": self.category,
            "timestamp": datetime.now().isoformat()
        }


# ---------------------------------------------------------------------------
# Configuração centralizada
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    timeout: int = 12
    retries: int = 2
    cache_ttl: int = 300  # 5 minutos
    rate_limit_interval: float = 1.0  # segundos entre chamadas
    max_query_length: int = 100
    enable_cache: bool = True
    enable_metrics: bool = True


DEFAULT_CONFIG = SourceConfig()


# ---------------------------------------------------------------------------
# Cache e Rate Limiting
# ---------------------------------------------------------------------------

class SourceCache:
    """Cache para resultados de fontes"""
    _cache: Dict[str, Tuple[Any, datetime]] = {}
    
    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        if not DEFAULT_CONFIG.enable_cache:
            return None
        if key in cls._cache:
            data, timestamp = cls._cache[key]
            if datetime.now() - timestamp < timedelta(seconds=DEFAULT_CONFIG.cache_ttl):
                return data
            del cls._cache[key]
        return None
    
    @classmethod
    def set(cls, key: str, data: Any):
        if DEFAULT_CONFIG.enable_cache:
            cls._cache[key] = (data, datetime.now())
    
    @classmethod
    def clear(cls):
        cls._cache.clear()


class RateLimiter:
    """Rate limiter para APIs gratuitas"""
    _calls: Dict[str, List[float]] = defaultdict(list)
    
    @classmethod
    def wait_if_needed(cls, source_name: str):
        now = time.time()
        calls = cls._calls[source_name]
        # Limpa chamadas antigas (últimos 60 segundos)
        calls = [t for t in calls if now - t < 60]
        cls._calls[source_name] = calls
        
        if calls and (now - calls[-1]) < DEFAULT_CONFIG.rate_limit_interval:
            sleep_time = DEFAULT_CONFIG.rate_limit_interval - (now - calls[-1])
            time.sleep(sleep_time)
        
        cls._calls[source_name].append(time.time())


class SourceMetrics:
    """Métricas e monitoramento das fontes"""
    _stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "calls": 0,
        "success": 0,
        "errors": 0,
        "total_time_ms": 0,
        "last_call": None,
        "last_error": None
    })
    
    @classmethod
    def record(cls, source_name: str, success: bool, response_time_ms: float, error: Optional[str] = None):
        if not DEFAULT_CONFIG.enable_metrics:
            return
        stats = cls._stats[source_name]
        stats["calls"] += 1
        stats["total_time_ms"] += response_time_ms
        stats["last_call"] = datetime.now().isoformat()
        
        if success:
            stats["success"] += 1
        else:
            stats["errors"] += 1
            if error:
                stats["last_error"] = error
    
    @classmethod
    def get_health(cls) -> Dict[str, Dict[str, Any]]:
        """Retorna métricas de saúde das fontes"""
        return {
            name: {
                "success_rate": s["success"] / s["calls"] if s["calls"] else 0,
                "avg_time_ms": s["total_time_ms"] / s["calls"] if s["calls"] else 0,
                "error_count": s["errors"],
                "total_calls": s["calls"],
                "last_call": s["last_call"],
                "last_error": s["last_error"]
            }
            for name, s in cls._stats.items()
        }
    
    @classmethod
    def get_unhealthy_sources(cls, min_success_rate: float = 0.5) -> List[str]:
        """Retorna fontes com baixa taxa de sucesso"""
        unhealthy = []
        for name, metrics in cls.get_health().items():
            if metrics["success_rate"] < min_success_rate and metrics["total_calls"] > 5:
                unhealthy.append(name)
        return unhealthy
    
    @classmethod
    def reset(cls):
        cls._stats.clear()


# ---------------------------------------------------------------------------
# HTTP helpers melhorados
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS = {
    "User-Agent": "AtenaIA/3.1 (research-bot; https://github.com/atena-ia)",
    "Accept": "application/json",
}


def sanitize_query(query: str, max_length: int = None) -> str:
    """Sanitiza query para evitar abuso e problemas de encoding"""
    if max_length is None:
        max_length = DEFAULT_CONFIG.max_query_length
    
    if not query:
        return "pesquisa"
    
    if len(query) > max_length:
        query = query[:max_length]
    
    # Remove caracteres potencialmente perigosos
    query = re.sub(r'[<>{}[\]|\\`]', '', query)
    return query.strip()


def _get(url: str, timeout: int = None, headers: Optional[Dict] = None) -> Any:
    """GET JSON com fallback para texto."""
    if timeout is None:
        timeout = DEFAULT_CONFIG.timeout
    
    h = {**_DEFAULT_HEADERS, **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _get_with_retry(url: str, source_name: str, **kwargs) -> Any:
    """GET com retry automático"""
    last_error = None
    
    for attempt in range(DEFAULT_CONFIG.retries):
        try:
            return _get(url, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < DEFAULT_CONFIG.retries - 1:
                time.sleep(1 * (attempt + 1))
    
    raise last_error


def _get_text(url: str, timeout: int = None, headers: Optional[Dict] = None) -> str:
    if timeout is None:
        timeout = DEFAULT_CONFIG.timeout
    
    h = {**_DEFAULT_HEADERS, **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _timed(fn, *args, **kwargs):
    """Executa função com medição de tempo e rate limiting.

    Os adaptadores legados podem passar o nome da fonte por posição e também
    por palavra-chave. O wrapper normaliza essa chamada antes de invocar a
    função HTTP interna.
    """
    source_name = kwargs.pop("source_name", None)
    if source_name is None:
        if not args:
            raise TypeError("_timed exige source_name")
        source_name, *args = args
    elif args and args[0] == source_name:
        args = args[1:]
    RateLimiter.wait_if_needed(source_name)
    
    t0 = time.time()
    error_msg = None
    
    try:
        # `_get_with_retry` precisa receber source_name para suas métricas,
        # mas os adaptadores antigos também o passam como primeiro argumento.
        if fn is _get_with_retry:
            result = fn(*args, source_name=source_name, **kwargs)
        else:
            result = fn(*args, **kwargs)
        ms = (time.time() - t0) * 1000
        SourceMetrics.record(source_name, True, ms)
        return result, ms, None
    except Exception as e:
        ms = (time.time() - t0) * 1000
        error_msg = str(e)
        SourceMetrics.record(source_name, False, ms, error_msg)
        return None, ms, error_msg


def _ok(source, data, ms, category=""):
    return ExtSourceResult(source=source, ok=True, details=data,
                           response_time_ms=ms, category=category)


def _err(source, err, ms, category=""):
    return ExtSourceResult(source=source, ok=False, details={"error": str(err)},
                           response_time_ms=ms, category=category)


# ===========================================================================
# CATEGORIA: IA / Machine Learning
# ===========================================================================

class HuggingFaceSource:
    NAME = "huggingface"
    WEIGHT = 0.92
    CATEGORY = "ai_ml"
    REQUIRES_KEY = False
    KEYWORDS = ["modelo", "llm", "transformer", "diffusion", "nlp", "ia", "ai", "ml",
                 "machine learning", "deep learning", "bert", "gpt", "stable diffusion"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{HuggingFaceSource.NAME}:{query}"
        
        # Check cache
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://huggingface.co/api/models?search={urllib.parse.quote(query)}&limit=5&sort=downloads"
        data, ms, err = _timed(_get_with_retry, HuggingFaceSource.NAME, url, source_name=HuggingFaceSource.NAME)
        
        if err or not data:
            result = _err(HuggingFaceSource.NAME, err, ms, HuggingFaceSource.CATEGORY)
        else:
            models = [
                {"id": m.get("modelId", ""), "downloads": m.get("downloads", 0),
                 "likes": m.get("likes", 0), "pipeline": m.get("pipeline_tag", "")}
                for m in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(HuggingFaceSource.NAME, {"models": models}, ms, HuggingFaceSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class HuggingFaceDatasetsSource:
    NAME = "huggingface_datasets"
    WEIGHT = 0.88
    CATEGORY = "ai_ml"
    REQUIRES_KEY = False
    KEYWORDS = ["dataset", "dados", "corpus", "benchmark", "treinamento"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{HuggingFaceDatasetsSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://huggingface.co/api/datasets?search={urllib.parse.quote(query)}&limit=5"
        data, ms, err = _timed(_get_with_retry, HuggingFaceDatasetsSource.NAME, url, source_name=HuggingFaceDatasetsSource.NAME)
        
        if err or not data:
            result = _err(HuggingFaceDatasetsSource.NAME, err, ms, HuggingFaceDatasetsSource.CATEGORY)
        else:
            datasets = [
                {"id": d.get("id", ""), "downloads": d.get("downloads", 0), "likes": d.get("likes", 0)}
                for d in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(HuggingFaceDatasetsSource.NAME, {"datasets": datasets}, ms, HuggingFaceDatasetsSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class PapersWithCodeSource:
    NAME = "paperswithcode"
    WEIGHT = 0.93
    CATEGORY = "ai_ml"
    REQUIRES_KEY = False
    KEYWORDS = ["paper", "código", "code", "benchmark", "sota", "state of the art",
                 "pesquisa", "research", "implementação"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{PapersWithCodeSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://paperswithcode.com/api/v1/papers/?q={urllib.parse.quote(query)}&items_per_page=5"
        data, ms, err = _timed(_get_with_retry, PapersWithCodeSource.NAME, url, source_name=PapersWithCodeSource.NAME)
        
        if err or not data:
            result = _err(PapersWithCodeSource.NAME, err, ms, PapersWithCodeSource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            papers = [
                {"title": p.get("title", ""), "stars": p.get("github_link", ""),
                 "url": p.get("url_pdf", "")}
                for p in results[:5]
            ]
            result = _ok(PapersWithCodeSource.NAME, {"papers": papers}, ms, PapersWithCodeSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Código / Desenvolvimento
# ===========================================================================

class LibrariesIOSource:
    NAME = "libraries_io"
    WEIGHT = 0.82
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["biblioteca", "library", "pacote", "package", "dependência", "versão",
                 "npm", "pypi", "gem", "nuget", "maven", "rubygems"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{LibrariesIOSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://libraries.io/api/search?q={urllib.parse.quote(query)}&per_page=5"
        data, ms, err = _timed(_get_with_retry, LibrariesIOSource.NAME, url, source_name=LibrariesIOSource.NAME)
        
        if err or not data:
            result = _err(LibrariesIOSource.NAME, err, ms, LibrariesIOSource.CATEGORY)
        else:
            libs = [
                {"name": l.get("name", ""), "platform": l.get("platform", ""),
                 "language": l.get("language", ""), "stars": l.get("stars", 0),
                 "latest": l.get("latest_release_number", "")}
                for l in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(LibrariesIOSource.NAME, {"libraries": libs}, ms, LibrariesIOSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class PyPISource:
    NAME = "pypi"
    WEIGHT = 0.85
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["python", "pip", "pypi", "pacote python", "biblioteca python"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{PyPISource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        # Busca direta no JSON do PyPI para o pacote exato
        url = f"https://pypi.org/pypi/{urllib.parse.quote(query)}/json"
        data, ms, err = _timed(_get_with_retry, PyPISource.NAME, url, source_name=PyPISource.NAME)
        
        if err or not data:
            # Fallback: busca via simple API
            url2 = f"https://pypi.org/search/?q={urllib.parse.quote(query)}&format=json"
            data, ms, err = _timed(_get_with_retry, PyPISource.NAME, url2, source_name=PyPISource.NAME)
        
        if err or not data:
            result = _err(PyPISource.NAME, err, ms, PyPISource.CATEGORY)
        else:
            info = data.get("info", {}) if isinstance(data, dict) else {}
            result = _ok(PyPISource.NAME, {
                "name": info.get("name", query),
                "version": info.get("version", ""),
                "summary": (info.get("summary") or "")[:200],
                "author": info.get("author", ""),
                "license": info.get("license", ""),
            }, ms, PyPISource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class GitLabSource:
    NAME = "gitlab"
    WEIGHT = 0.80
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["gitlab", "repositório", "repo", "código", "projeto", "git"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{GitLabSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://gitlab.com/api/v4/projects?search={urllib.parse.quote(query)}&order_by=star_count&per_page=5"
        data, ms, err = _timed(_get_with_retry, GitLabSource.NAME, url, source_name=GitLabSource.NAME)
        
        if err or not data:
            result = _err(GitLabSource.NAME, err, ms, GitLabSource.CATEGORY)
        else:
            projects = [
                {"name": p.get("name", ""), "stars": p.get("star_count", 0),
                 "url": p.get("web_url", ""), "lang": p.get("main_language", "")}
                for p in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(GitLabSource.NAME, {"projects": projects}, ms, GitLabSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class RubyGemsSource:
    NAME = "rubygems"
    WEIGHT = 0.75
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["ruby", "gem", "rails", "rubygems"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{RubyGemsSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://rubygems.org/api/v1/search.json?query={urllib.parse.quote(query)}&per_page=5"
        data, ms, err = _timed(_get_with_retry, RubyGemsSource.NAME, url, source_name=RubyGemsSource.NAME)
        
        if err or not data:
            result = _err(RubyGemsSource.NAME, err, ms, RubyGemsSource.CATEGORY)
        else:
            gems = [
                {"name": g.get("name", ""), "version": g.get("version", ""),
                 "downloads": g.get("downloads", 0), "info": (g.get("info") or "")[:150]}
                for g in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(RubyGemsSource.NAME, {"gems": gems}, ms, RubyGemsSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class NuGetSource:
    NAME = "nuget"
    WEIGHT = 0.75
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["nuget", "dotnet", ".net", "c#", "csharp", "asp.net"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{NuGetSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://azuresearch-usnc.nuget.org/query?q={urllib.parse.quote(query)}&take=5"
        data, ms, err = _timed(_get_with_retry, NuGetSource.NAME, url, source_name=NuGetSource.NAME)
        
        if err or not data:
            result = _err(NuGetSource.NAME, err, ms, NuGetSource.CATEGORY)
        else:
            pkgs = [
                {"id": p.get("id", ""), "version": p.get("version", ""),
                 "description": (p.get("description") or "")[:150],
                 "downloads": p.get("totalDownloads", 0)}
                for p in data.get("data", [])[:5]
            ]
            result = _ok(NuGetSource.NAME, {"packages": pkgs}, ms, NuGetSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class SourcegraphSource:
    NAME = "sourcegraph"
    WEIGHT = 0.78
    CATEGORY = "code"
    REQUIRES_KEY = False
    KEYWORDS = ["código fonte", "source code", "search code", "busca código"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{SourcegraphSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://sourcegraph.com/.api/search/stream?"
            f"q={urllib.parse.quote(query)}&v=V3&t=literal&display=5"
        )
        
        try:
            t0 = time.time()
            RateLimiter.wait_if_needed(SourcegraphSource.NAME)
            
            req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=DEFAULT_CONFIG.timeout) as resp:
                raw = resp.read(4096).decode("utf-8", errors="replace")
            
            ms = (time.time() - t0) * 1000
            lines = [l for l in raw.splitlines() if l.startswith("data:")][:3]
            results = []
            
            for line in lines:
                try:
                    obj = json.loads(line[5:])
                    if isinstance(obj, dict) and "results" in obj:
                        for r in obj["results"][:2]:
                            results.append({
                                "repo": r.get("repository", {}).get("name", ""),
                                "file": r.get("file", {}).get("path", ""),
                            })
                except Exception:
                    pass
            
            result = _ok(SourcegraphSource.NAME, {"results": results}, ms, SourcegraphSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result
            
        except Exception as e:
            ms = (time.time() - t0) * 1000 if 't0' in locals() else 0
            result = _err(SourcegraphSource.NAME, e, ms, SourcegraphSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result


# ===========================================================================
# CATEGORIA: Ciência / Pesquisa
# ===========================================================================

class DOAJSource:
    NAME = "doaj"
    WEIGHT = 0.88
    CATEGORY = "research"
    REQUIRES_KEY = False
    KEYWORDS = ["artigo", "journal", "periódico", "open access", "publicação", "ciência"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{DOAJSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://doaj.org/api/search/articles/{urllib.parse.quote(query)}?pageSize=5"
        data, ms, err = _timed(_get_with_retry, DOAJSource.NAME, url, source_name=DOAJSource.NAME)
        
        if err or not data:
            result = _err(DOAJSource.NAME, err, ms, DOAJSource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            articles = [
                {
                    "title": r.get("bibjson", {}).get("title", ""),
                    "year": r.get("bibjson", {}).get("year", ""),
                    "journal": r.get("bibjson", {}).get("journal", {}).get("title", ""),
                }
                for r in results[:5]
            ]
            result = _ok(DOAJSource.NAME, {"articles": articles}, ms, DOAJSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class CORESource:
    NAME = "core_ac"
    WEIGHT = 0.87
    CATEGORY = "research"
    REQUIRES_KEY = False
    KEYWORDS = ["artigo", "paper", "open access", "pesquisa", "acadêmico"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{CORESource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.core.ac.uk/v3/search/works?q={urllib.parse.quote(query)}&limit=5&stats=false"
        data, ms, err = _timed(_get_with_retry, CORESource.NAME, url, source_name=CORESource.NAME)
        
        if err or not data:
            result = _err(CORESource.NAME, err, ms, CORESource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            papers = [
                {"title": r.get("title", ""), "year": r.get("yearPublished", ""),
                 "abstract": (r.get("abstract") or "")[:200]}
                for r in results[:5]
            ]
            result = _ok(CORESource.NAME, {"papers": papers}, ms, CORESource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class BioRxivSource:
    NAME = "biorxiv"
    WEIGHT = 0.89
    CATEGORY = "research"
    REQUIRES_KEY = False
    KEYWORDS = ["biologia", "medicina", "preprint", "bioinformática", "genomica",
                 "proteína", "célula", "vírus", "bactéria", "neurociência"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{BioRxivSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://api.biorxiv.org/details/biorxiv/"
            f"{urllib.parse.quote(query)}/0/5/json"
        )
        data, ms, err = _timed(_get_with_retry, BioRxivSource.NAME, url, source_name=BioRxivSource.NAME)
        
        if err or not isinstance(data, dict):
            result = _err(BioRxivSource.NAME, err, ms, BioRxivSource.CATEGORY)
        else:
            collection = data.get("collection", [])
            papers = [
                {"title": p.get("title", ""), "date": p.get("date", ""),
                 "doi": p.get("doi", ""), "abstract": (p.get("abstract") or "")[:200]}
                for p in collection[:5]
            ]
            result = _ok(BioRxivSource.NAME, {"papers": papers}, ms, BioRxivSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class GBIFSource:
    NAME = "gbif"
    WEIGHT = 0.84
    CATEGORY = "science"
    REQUIRES_KEY = False
    KEYWORDS = ["espécie", "animal", "planta", "biodiversidade", "taxonomia",
                 "biologia", "ecologia", "occurrence", "flora", "fauna"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{GBIFSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.gbif.org/v1/species/search?q={urllib.parse.quote(query)}&limit=5"
        data, ms, err = _timed(_get_with_retry, GBIFSource.NAME, url, source_name=GBIFSource.NAME)
        
        if err or not data:
            result = _err(GBIFSource.NAME, err, ms, GBIFSource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            species = [
                {"name": r.get("scientificName", ""), "kingdom": r.get("kingdom", ""),
                 "status": r.get("taxonomicStatus", ""), "rank": r.get("rank", "")}
                for r in results[:5]
            ]
            result = _ok(GBIFSource.NAME, {"species": species}, ms, GBIFSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class NASASource:
    NAME = "nasa"
    WEIGHT = 0.91
    CATEGORY = "science"
    REQUIRES_KEY = False
    KEYWORDS = ["nasa", "espaço", "space", "astronomia", "planeta", "foguete",
                 "missão espacial", "satélite", "astrofísica", "apod"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{NASASource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://images-api.nasa.gov/search?q={urllib.parse.quote(query)}&media_type=image&page_size=5"
        data, ms, err = _timed(_get_with_retry, NASASource.NAME, url, source_name=NASASource.NAME)
        
        if err or not data:
            result = _err(NASASource.NAME, err, ms, NASASource.CATEGORY)
        else:
            items = data.get("collection", {}).get("items", []) if isinstance(data, dict) else []
            results = [
                {"title": i.get("data", [{}])[0].get("title", ""),
                 "description": (i.get("data", [{}])[0].get("description") or "")[:200],
                 "date": i.get("data", [{}])[0].get("date_created", "")}
                for i in items[:5] if i.get("data")
            ]
            result = _ok(NASASource.NAME, {"results": results}, ms, NASASource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class WikinewsSource:
    NAME = "wikinews"
    WEIGHT = 0.70
    CATEGORY = "news"
    REQUIRES_KEY = False
    KEYWORDS = ["notícia", "news", "atual", "evento", "acontecimento"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{WikinewsSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://en.wikinews.org/w/api.php?"
            f"action=query&list=search&srsearch={urllib.parse.quote(query)}"
            f"&format=json&srlimit=5&srprop=snippet"
        )
        data, ms, err = _timed(_get_with_retry, WikinewsSource.NAME, url, source_name=WikinewsSource.NAME)
        
        if err or not data:
            result = _err(WikinewsSource.NAME, err, ms, WikinewsSource.CATEGORY)
        else:
            results = data.get("query", {}).get("search", []) if isinstance(data, dict) else []
            news = [
                {"title": r.get("title", ""),
                 "snippet": (r.get("snippet") or "").replace("<span class='searchmatch'>", "")
                             .replace("</span>", "")[:200]}
                for r in results[:5]
            ]
            result = _ok(WikinewsSource.NAME, {"news": news}, ms, WikinewsSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class GDELTSource:
    NAME = "gdelt"
    WEIGHT = 0.82
    CATEGORY = "news"
    REQUIRES_KEY = False
    KEYWORDS = ["notícia global", "mídia", "cobertura", "evento mundial", "geopolítica"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{GDELTSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={urllib.parse.quote(query)}&mode=artlist&maxrecords=5&format=json"
        )
        data, ms, err = _timed(_get_with_retry, GDELTSource.NAME, url, source_name=GDELTSource.NAME)
        
        if err or not data:
            result = _err(GDELTSource.NAME, err, ms, GDELTSource.CATEGORY)
        else:
            articles = data.get("articles", []) if isinstance(data, dict) else []
            results = [
                {"title": a.get("title", ""), "url": a.get("url", ""),
                 "seendate": a.get("seendate", ""), "domain": a.get("domain", "")}
                for a in articles[:5]
            ]
            result = _ok(GDELTSource.NAME, {"articles": results}, ms, GDELTSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Finanças / Economia
# ===========================================================================

class FrankfurterSource:
    NAME = "frankfurter"
    WEIGHT = 0.88
    CATEGORY = "finance"
    REQUIRES_KEY = False
    KEYWORDS = ["câmbio", "moeda", "exchange", "dólar", "euro", "real", "conversão",
                 "taxa", "forex", "brl", "usd", "eur"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        cache_key = f"{FrankfurterSource.NAME}:rates"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = "https://api.frankfurter.app/latest?base=BRL"
        data, ms, err = _timed(_get_with_retry, FrankfurterSource.NAME, url, source_name=FrankfurterSource.NAME)
        
        if err or not data:
            result = _err(FrankfurterSource.NAME, err, ms, FrankfurterSource.CATEGORY)
        else:
            rates = data.get("rates", {}) if isinstance(data, dict) else {}
            key_currencies = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "ARS"]
            filtered = {k: rates[k] for k in key_currencies if k in rates}
            result = _ok(FrankfurterSource.NAME, {
                "base": "BRL", "date": data.get("date", ""), "rates": filtered
            }, ms, FrankfurterSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class CoinGeckoExtSource:
    NAME = "coingecko_ext"
    WEIGHT = 0.87
    CATEGORY = "finance"
    REQUIRES_KEY = False
    KEYWORDS = ["crypto", "bitcoin", "ethereum", "criptomoeda", "token", "defi",
                 "blockchain", "nft", "web3", "altcoin"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{CoinGeckoExtSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(query)}"
        data, ms, err = _timed(_get_with_retry, CoinGeckoExtSource.NAME, url, source_name=CoinGeckoExtSource.NAME)
        
        if err or not data:
            result = _err(CoinGeckoExtSource.NAME, err, ms, CoinGeckoExtSource.CATEGORY)
        else:
            coins = data.get("coins", []) if isinstance(data, dict) else []
            top = [
                {"id": c.get("id", ""), "name": c.get("name", ""),
                 "symbol": c.get("symbol", ""), "rank": c.get("market_cap_rank")}
                for c in coins[:5]
            ]
            
            if top:
                coin_id = top[0]["id"]
                price_url = (
                    f"https://api.coingecko.com/api/v3/simple/price?"
                    f"ids={coin_id}&vs_currencies=brl,usd,eur"
                )
                price_data, ms2, _ = _timed(_get_with_retry, CoinGeckoExtSource.NAME, price_url, source_name=CoinGeckoExtSource.NAME)
                price = price_data.get(coin_id, {}) if isinstance(price_data, dict) else {}
                result = _ok(CoinGeckoExtSource.NAME, {
                    "top_coins": top, "price": price, "coin": coin_id
                }, ms + ms2, CoinGeckoExtSource.CATEGORY)
            else:
                result = _ok(CoinGeckoExtSource.NAME, {"top_coins": top}, ms, CoinGeckoExtSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class WorldBankSource:
    NAME = "world_bank"
    WEIGHT = 0.85
    CATEGORY = "finance"
    REQUIRES_KEY = False
    KEYWORDS = ["pib", "gdp", "economia", "banco mundial", "indicador econômico",
                 "crescimento", "inflação", "desemprego", "pobreza", "desenvolvimento"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{WorldBankSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://api.worldbank.org/v2/indicator?"
            f"format=json&per_page=5&source=2&q={urllib.parse.quote(query)}"
        )
        data, ms, err = _timed(_get_with_retry, WorldBankSource.NAME, url, source_name=WorldBankSource.NAME)
        
        if err or not isinstance(data, list) or len(data) < 2:
            result = _err(WorldBankSource.NAME, err or "formato inesperado", ms, WorldBankSource.CATEGORY)
        else:
            indicators = [
                {"id": i.get("id", ""), "name": i.get("name", ""),
                 "sourceNote": (i.get("sourceNote") or "")[:200]}
                for i in (data[1] or [])[:5]
            ]
            result = _ok(WorldBankSource.NAME, {"indicators": indicators}, ms, WorldBankSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Saúde
# ===========================================================================

class OpenFDASource:
    NAME = "openfda"
    WEIGHT = 0.91
    CATEGORY = "health"
    REQUIRES_KEY = False
    KEYWORDS = ["medicamento", "droga", "drug", "fda", "efeito colateral", "remédio",
                 "farmácia", "bula", "adverse event", "recall"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{OpenFDASource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://api.fda.gov/drug/label.json?"
            f"search=openfda.brand_name:{urllib.parse.quote(query)}&limit=3"
        )
        data, ms, err = _timed(_get_with_retry, OpenFDASource.NAME, url, source_name=OpenFDASource.NAME)
        
        if err or not data:
            url2 = f"https://api.fda.gov/drug/label.json?search={urllib.parse.quote(query)}&limit=3"
            data, ms, err = _timed(_get_with_retry, OpenFDASource.NAME, url2, source_name=OpenFDASource.NAME)
        
        if err or not data:
            result = _err(OpenFDASource.NAME, err, ms, OpenFDASource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            drugs = [
                {
                    "brand": r.get("openfda", {}).get("brand_name", [""])[0] if r.get("openfda", {}).get("brand_name") else "",
                    "generic": r.get("openfda", {}).get("generic_name", [""])[0] if r.get("openfda", {}).get("generic_name") else "",
                    "purpose": (r.get("purpose", [""])[0] if r.get("purpose") else "")[:200],
                    "warnings": (r.get("warnings", [""])[0] if r.get("warnings") else "")[:300],
                }
                for r in results[:3]
            ]
            result = _ok(OpenFDASource.NAME, {"drugs": drugs}, ms, OpenFDASource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class RxNormSource:
    NAME = "rxnorm"
    WEIGHT = 0.89
    CATEGORY = "health"
    REQUIRES_KEY = False
    KEYWORDS = ["medicamento", "droga", "rxnorm", "princípio ativo", "interação medicamentosa"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{RxNormSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://rxnav.nlm.nih.gov/REST/drugs.json?name={urllib.parse.quote(query)}"
        data, ms, err = _timed(_get_with_retry, RxNormSource.NAME, url, source_name=RxNormSource.NAME)
        
        if err or not data:
            result = _err(RxNormSource.NAME, err, ms, RxNormSource.CATEGORY)
        else:
            drug_group = data.get("drugGroup", {}) if isinstance(data, dict) else {}
            concepts = drug_group.get("conceptGroup", [])
            drugs = []
            for group in concepts[:3]:
                for prop in (group.get("conceptProperties") or [])[:3]:
                    drugs.append({
                        "rxcui": prop.get("rxcui", ""),
                        "name": prop.get("name", ""),
                        "tty": prop.get("tty", ""),
                    })
            result = _ok(RxNormSource.NAME, {"drugs": drugs}, ms, RxNormSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Geografia / Localização
# ===========================================================================

class NominatimSource:
    NAME = "nominatim"
    WEIGHT = 0.82
    CATEGORY = "geo"
    REQUIRES_KEY = False
    KEYWORDS = ["endereço", "local", "cidade", "país", "coordenadas", "mapa",
                 "latitude", "longitude", "geolocalização", "bairro"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{NominatimSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://nominatim.openstreetmap.org/search?"
            f"q={urllib.parse.quote(query)}&format=json&limit=5&addressdetails=1"
        )
        headers = {"User-Agent": "AtenaIA/3.1 nominatim-query"}
        data, ms, err = _timed(_get_with_retry, NominatimSource.NAME, url, headers=headers, source_name=NominatimSource.NAME)
        
        if err or not data:
            result = _err(NominatimSource.NAME, err, ms, NominatimSource.CATEGORY)
        else:
            places = [
                {
                    "display": p.get("display_name", "")[:200],
                    "lat": p.get("lat", ""),
                    "lon": p.get("lon", ""),
                    "type": p.get("type", ""),
                    "country": p.get("address", {}).get("country", ""),
                }
                for p in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(NominatimSource.NAME, {"places": places}, ms, NominatimSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class OpenElevationSource:
    NAME = "open_elevation"
    WEIGHT = 0.75
    CATEGORY = "geo"
    REQUIRES_KEY = False
    KEYWORDS = ["elevação", "altitude", "terreno", "relevo", "montanha"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{OpenElevationSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        try:
            t0 = time.time()
            RateLimiter.wait_if_needed(OpenElevationSource.NAME)
            
            nom_url = (
                f"https://nominatim.openstreetmap.org/search?"
                f"q={urllib.parse.quote(query)}&format=json&limit=1"
            )
            nom = _get_with_retry(nom_url, OpenElevationSource.NAME, headers={"User-Agent": "AtenaIA/3.1"})
            
            if not nom or not isinstance(nom, list):
                ms = (time.time() - t0) * 1000
                result = _err(OpenElevationSource.NAME, "lugar não encontrado", ms, OpenElevationSource.CATEGORY)
                SourceCache.set(cache_key, result)
                return result
            
            lat, lon = nom[0].get("lat", "0"), nom[0].get("lon", "0")
            elev_url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
            elev = _get_with_retry(elev_url, OpenElevationSource.NAME)
            results = elev.get("results", [{}]) if isinstance(elev, dict) else [{}]
            ms = (time.time() - t0) * 1000
            
            result = _ok(OpenElevationSource.NAME, {
                "place": nom[0].get("display_name", query)[:150],
                "lat": lat, "lon": lon,
                "elevation_m": results[0].get("elevation", "N/A"),
            }, ms, OpenElevationSource.CATEGORY)
            
            SourceCache.set(cache_key, result)
            return result
            
        except Exception as e:
            ms = (time.time() - t0) * 1000 if 't0' in locals() else 0
            result = _err(OpenElevationSource.NAME, e, ms, OpenElevationSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result


class IPAPISource:
    NAME = "ip_api"
    WEIGHT = 0.80
    CATEGORY = "geo"
    REQUIRES_KEY = False
    KEYWORDS = ["ip", "geolocalização ip", "país ip", "localização ip"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{IPAPISource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"http://ip-api.com/json/{urllib.parse.quote(query)}?fields=status,country,regionName,city,isp,org,lat,lon"
        data, ms, err = _timed(_get_with_retry, IPAPISource.NAME, url, source_name=IPAPISource.NAME)
        
        if err or not data:
            result = _err(IPAPISource.NAME, err, ms, IPAPISource.CATEGORY)
        elif isinstance(data, dict) and data.get("status") == "success":
            result = _ok(IPAPISource.NAME, {
                "country": data.get("country", ""),
                "region": data.get("regionName", ""),
                "city": data.get("city", ""),
                "isp": data.get("isp", ""),
                "lat": data.get("lat"), "lon": data.get("lon"),
            }, ms, IPAPISource.CATEGORY)
        else:
            result = _err(IPAPISource.NAME, data.get("message", "erro"), ms, IPAPISource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class RestCountriesSource:
    NAME = "rest_countries"
    WEIGHT = 0.85
    CATEGORY = "geo"
    REQUIRES_KEY = False
    KEYWORDS = ["país", "country", "capital", "população", "bandeira", "idioma",
                 "moeda", "continente", "nação"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{RestCountriesSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://restcountries.com/v3.1/name/{urllib.parse.quote(query)}?fields=name,capital,population,languages,currencies,flags,region,area"
        data, ms, err = _timed(_get_with_retry, RestCountriesSource.NAME, url, source_name=RestCountriesSource.NAME)
        
        if err or not data:
            result = _err(RestCountriesSource.NAME, err, ms, RestCountriesSource.CATEGORY)
        else:
            countries = []
            for c in (data if isinstance(data, list) else [])[:3]:
                currencies = list(c.get("currencies", {}).keys())
                languages = list(c.get("languages", {}).values())
                countries.append({
                    "name": c.get("name", {}).get("common", ""),
                    "official": c.get("name", {}).get("official", ""),
                    "capital": (c.get("capital") or [""])[0],
                    "population": c.get("population", 0),
                    "region": c.get("region", ""),
                    "area_km2": c.get("area", 0),
                    "languages": languages[:3],
                    "currencies": currencies[:2],
                })
            result = _ok(RestCountriesSource.NAME, {"countries": countries}, ms, RestCountriesSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Cultura / Entretenimento
# ===========================================================================

class MusicBrainzSource:
    NAME = "musicbrainz"
    WEIGHT = 0.82
    CATEGORY = "culture"
    REQUIRES_KEY = False
    KEYWORDS = ["música", "artista", "álbum", "banda", "canção", "disco",
                 "show", "concert", "gravadora"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{MusicBrainzSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://musicbrainz.org/ws/2/recording/"
            f"?query={urllib.parse.quote(query)}&fmt=json&limit=5"
        )
        headers = {"User-Agent": "AtenaIA/3.1 (atena@atena.ia)"}
        data, ms, err = _timed(_get_with_retry, MusicBrainzSource.NAME, url, headers=headers, source_name=MusicBrainzSource.NAME)
        
        if err or not data:
            result = _err(MusicBrainzSource.NAME, err, ms, MusicBrainzSource.CATEGORY)
        else:
            recordings = data.get("recordings", []) if isinstance(data, dict) else []
            tracks = [
                {
                    "title": r.get("title", ""),
                    "artist": (r.get("artist-credit") or [{}])[0].get("artist", {}).get("name", ""),
                    "length_ms": r.get("length", 0),
                    "releases": len(r.get("releases", [])),
                }
                for r in recordings[:5]
            ]
            result = _ok(MusicBrainzSource.NAME, {"tracks": tracks}, ms, MusicBrainzSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class TVMazeSource:
    NAME = "tvmaze"
    WEIGHT = 0.78
    CATEGORY = "culture"
    REQUIRES_KEY = False
    KEYWORDS = ["série", "tv", "show", "episódio", "netflix", "streaming", "programa",
                 "temporada", "elenco", "televisão"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{TVMazeSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.tvmaze.com/search/shows?q={urllib.parse.quote(query)}"
        data, ms, err = _timed(_get_with_retry, TVMazeSource.NAME, url, source_name=TVMazeSource.NAME)
        
        if err or not data:
            result = _err(TVMazeSource.NAME, err, ms, TVMazeSource.CATEGORY)
        else:
            shows = [
                {
                    "name": s.get("show", {}).get("name", ""),
                    "status": s.get("show", {}).get("status", ""),
                    "premiered": s.get("show", {}).get("premiered", ""),
                    "rating": s.get("show", {}).get("rating", {}).get("average"),
                    "genres": s.get("show", {}).get("genres", []),
                    "summary": (s.get("show", {}).get("summary") or "")
                                .replace("<p>", "").replace("</p>", "").replace("<b>", "")
                                .replace("</b>", "")[:200],
                }
                for s in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(TVMazeSource.NAME, {"shows": shows}, ms, TVMazeSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class OpenLibraryExtSource:
    NAME = "openlibrary_ext"
    WEIGHT = 0.80
    CATEGORY = "culture"
    REQUIRES_KEY = False
    KEYWORDS = ["livro", "book", "autor", "isbn", "literatura", "leitura", "publicação"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{OpenLibraryExtSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(query)}&limit=5&fields=title,author_name,first_publish_year,subject,isbn"
        data, ms, err = _timed(_get_with_retry, OpenLibraryExtSource.NAME, url, source_name=OpenLibraryExtSource.NAME)
        
        if err or not data:
            result = _err(OpenLibraryExtSource.NAME, err, ms, OpenLibraryExtSource.CATEGORY)
        else:
            docs = data.get("docs", []) if isinstance(data, dict) else []
            books = [
                {
                    "title": d.get("title", ""),
                    "authors": (d.get("author_name") or [])[:2],
                    "year": d.get("first_publish_year", ""),
                    "subjects": (d.get("subject") or [])[:3],
                }
                for d in docs[:5]
            ]
            result = _ok(OpenLibraryExtSource.NAME, {
                "books": books, "total": data.get("numFound", 0)
            }, ms, OpenLibraryExtSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class WikidataSource:
    NAME = "wikidata_ext"
    WEIGHT = 0.87
    CATEGORY = "knowledge"
    REQUIRES_KEY = False
    KEYWORDS = ["entidade", "fato", "conhecimento", "conceito", "definição",
                 "pessoa famosa", "lugar", "organização"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{WikidataSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://www.wikidata.org/w/api.php?"
            f"action=wbsearchentities&search={urllib.parse.quote(query)}"
            f"&language=pt&format=json&limit=5&type=item"
        )
        data, ms, err = _timed(_get_with_retry, WikidataSource.NAME, url, source_name=WikidataSource.NAME)
        
        if err or not data:
            result = _err(WikidataSource.NAME, err, ms, WikidataSource.CATEGORY)
        else:
            results = data.get("search", []) if isinstance(data, dict) else []
            entities = [
                {
                    "id": r.get("id", ""),
                    "label": r.get("label", ""),
                    "description": r.get("description", ""),
                    "url": r.get("url", ""),
                }
                for r in results[:5]
            ]
            result = _ok(WikidataSource.NAME, {"entities": entities}, ms, WikidataSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class GoogleBooksSource:
    NAME = "google_books"
    WEIGHT = 0.85
    CATEGORY = "culture"
    REQUIRES_KEY = False
    KEYWORDS = ["livro", "book", "autor", "isbn", "editora", "publicação"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{GoogleBooksSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=5"
        data, ms, err = _timed(_get_with_retry, GoogleBooksSource.NAME, url, source_name=GoogleBooksSource.NAME)
        
        if err or not data:
            result = _err(GoogleBooksSource.NAME, err, ms, GoogleBooksSource.CATEGORY)
        else:
            books = []
            for item in data.get("items", [])[:5]:
                vol = item.get("volumeInfo", {})
                books.append({
                    "title": vol.get("title", ""),
                    "authors": vol.get("authors", [])[:3],
                    "publisher": vol.get("publisher", ""),
                    "published_date": vol.get("publishedDate", ""),
                    "description": (vol.get("description") or "")[:200],
                    "page_count": vol.get("pageCount", 0),
                    "categories": vol.get("categories", [])[:3],
                })
            result = _ok(GoogleBooksSource.NAME, {
                "books": books,
                "total_items": data.get("totalItems", 0)
            }, ms, GoogleBooksSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Governança / Dados Abertos
# ===========================================================================

class DadosAbertosGovBRSource:
    NAME = "dados_abertos_br"
    WEIGHT = 0.85
    CATEGORY = "governance"
    REQUIRES_KEY = False
    KEYWORDS = ["governo brasil", "dados abertos", "ibge", "transparência", "licitação",
                 "orçamento", "federal", "municipal", "estadual", "brasil"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{DadosAbertosGovBRSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://dados.gov.br/api/3/action/package_search?"
            f"q={urllib.parse.quote(query)}&rows=5"
        )
        data, ms, err = _timed(_get_with_retry, DadosAbertosGovBRSource.NAME, url, source_name=DadosAbertosGovBRSource.NAME)
        
        if err or not data:
            result = _err(DadosAbertosGovBRSource.NAME, err, ms, DadosAbertosGovBRSource.CATEGORY)
        else:
            results = data.get("result", {}).get("results", []) if isinstance(data, dict) else []
            datasets = [
                {
                    "title": r.get("title", ""),
                    "organization": r.get("organization", {}).get("title", "") if r.get("organization") else "",
                    "notes": (r.get("notes") or "")[:200],
                    "resources": len(r.get("resources", [])),
                }
                for r in results[:5]
            ]
            result = _ok(DadosAbertosGovBRSource.NAME, {
                "datasets": datasets, "total": data.get("result", {}).get("count", 0)
            }, ms, DadosAbertosGovBRSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class IBGESource:
    NAME = "ibge"
    WEIGHT = 0.88
    CATEGORY = "governance"
    REQUIRES_KEY = False
    KEYWORDS = ["ibge", "população brasil", "município", "cidade brasileira", "censo",
                 "estatística brasil", "dados demográficos"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{IBGESource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios?nome={urllib.parse.quote(query)}"
        data, ms, err = _timed(_get_with_retry, IBGESource.NAME, url, source_name=IBGESource.NAME)
        
        if err or not data:
            result = _err(IBGESource.NAME, err, ms, IBGESource.CATEGORY)
        else:
            municipios = [
                {
                    "id": m.get("id", ""),
                    "nome": m.get("nome", ""),
                    "uf": m.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("sigla", ""),
                    "regiao": m.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("regiao", {}).get("nome", ""),
                }
                for m in (data if isinstance(data, list) else [])[:5]
            ]
            result = _ok(IBGESource.NAME, {"municipios": municipios}, ms, IBGESource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class ProPublicaCongressSource:
    NAME = "propublica_congress"
    WEIGHT = 0.83
    CATEGORY = "governance"
    REQUIRES_KEY = False
    KEYWORDS = ["congresso", "lei", "legislação", "senado", "câmara", "política",
                 "votação", "governo", "democracia"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{ProPublicaCongressSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://api.propublica.org/congress/v1/bills/search.json?"
            f"query={urllib.parse.quote(query)}&sort=score&dir=desc"
        )
        
        try:
            data, ms, err = _timed(_get_with_retry, ProPublicaCongressSource.NAME, url, 
                                  headers={"X-API-Key": "DEMO"}, source_name=ProPublicaCongressSource.NAME)
            
            if err:
                result = _err(ProPublicaCongressSource.NAME, "API key necessária (gratuita)", ms,
                            ProPublicaCongressSource.CATEGORY)
            else:
                results = data.get("results", [{}])[0].get("bills", []) if isinstance(data, dict) else []
                bills = [
                    {"title": b.get("title", ""), "number": b.get("number", ""),
                     "sponsor": b.get("sponsor_name", ""), "status": b.get("active", "")}
                    for b in results[:5]
                ]
                result = _ok(ProPublicaCongressSource.NAME, {"bills": bills}, ms,
                           ProPublicaCongressSource.CATEGORY)
            
            SourceCache.set(cache_key, result)
            return result
            
        except Exception as e:
            result = _err(ProPublicaCongressSource.NAME, e, 0, ProPublicaCongressSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result


# ===========================================================================
# CATEGORIA: Infraestrutura / Segurança
# ===========================================================================

class CRTShSource:
    NAME = "crt_sh"
    WEIGHT = 0.80
    CATEGORY = "security"
    REQUIRES_KEY = False
    KEYWORDS = ["certificado ssl", "domínio", "tls", "https", "subdomínio",
                 "certificate transparency", "dns"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{CRTShSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://crt.sh/?q={urllib.parse.quote(query)}&output=json&limit=10"
        data, ms, err = _timed(_get_with_retry, CRTShSource.NAME, url, source_name=CRTShSource.NAME)
        
        if err or not data:
            result = _err(CRTShSource.NAME, err, ms, CRTShSource.CATEGORY)
        else:
            certs = [
                {
                    "cn": c.get("common_name", ""),
                    "issuer": c.get("issuer_name", "")[:80],
                    "not_before": c.get("not_before", ""),
                    "not_after": c.get("not_after", ""),
                }
                for c in (data if isinstance(data, list) else [])[:10]
            ]
            # Deduplica por CN
            seen = set()
            unique = []
            for c in certs:
                if c["cn"] not in seen:
                    seen.add(c["cn"])
                    unique.append(c)
            result = _ok(CRTShSource.NAME, {"certificates": unique[:5]}, ms, CRTShSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class ShodanInternetDBSource:
    NAME = "shodan_internetdb"
    WEIGHT = 0.83
    CATEGORY = "security"
    REQUIRES_KEY = False
    KEYWORDS = ["ip scanning", "portas abertas", "vulnerabilidade", "shodan",
                 "serviço exposto", "banner"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{ShodanInternetDBSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://internetdb.shodan.io/{urllib.parse.quote(query)}"
        data, ms, err = _timed(_get_with_retry, ShodanInternetDBSource.NAME, url, source_name=ShodanInternetDBSource.NAME)
        
        if err or not data:
            result = _err(ShodanInternetDBSource.NAME, err, ms, ShodanInternetDBSource.CATEGORY)
        elif isinstance(data, dict) and "detail" in data:
            result = _err(ShodanInternetDBSource.NAME, data["detail"], ms, ShodanInternetDBSource.CATEGORY)
        else:
            result = _ok(ShodanInternetDBSource.NAME, {
                "ip": data.get("ip", query),
                "ports": data.get("ports", []),
                "cpes": data.get("cpes", [])[:5],
                "vulns": data.get("vulns", [])[:5],
                "hostnames": data.get("hostnames", [])[:5],
                "tags": data.get("tags", []),
            }, ms, ShodanInternetDBSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class HaveIBeenPwnedSource:
    NAME = "haveibeenpwned_breaches"
    WEIGHT = 0.82
    CATEGORY = "security"
    REQUIRES_KEY = False
    KEYWORDS = ["breach", "vazamento", "senha vazada", "dados comprometidos", "hack",
                 "pwned", "segurança"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{HaveIBeenPwnedSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://haveibeenpwned.com/api/v3/breach/{urllib.parse.quote(query)}"
        headers = {"hibp-api-key": "none", "User-Agent": "AtenaIA/3.1"}
        
        try:
            t0 = time.time()
            RateLimiter.wait_if_needed(HaveIBeenPwnedSource.NAME)
            
            req = urllib.request.Request(url, headers={**_DEFAULT_HEADERS, **headers})
            with urllib.request.urlopen(req, timeout=DEFAULT_CONFIG.timeout) as resp:
                raw = resp.read().decode("utf-8")
            ms = (time.time() - t0) * 1000
            data = json.loads(raw)
            
            result = _ok(HaveIBeenPwnedSource.NAME, {
                "name": data.get("Name", ""),
                "title": data.get("Title", ""),
                "breach_date": data.get("BreachDate", ""),
                "pwn_count": data.get("PwnCount", 0),
                "data_classes": data.get("DataClasses", [])[:8],
                "description": (data.get("Description") or "")[:300],
            }, ms, HaveIBeenPwnedSource.CATEGORY)
            
            SourceCache.set(cache_key, result)
            return result
            
        except urllib.error.HTTPError as e:
            ms = (time.time() - t0) * 1000 if 't0' in locals() else 0
            if e.code == 404:
                result = _ok(HaveIBeenPwnedSource.NAME, {"status": "não encontrado"}, ms,
                           HaveIBeenPwnedSource.CATEGORY)
            else:
                result = _err(HaveIBeenPwnedSource.NAME, str(e), ms, HaveIBeenPwnedSource.CATEGORY)
            
            SourceCache.set(cache_key, result)
            return result
            
        except Exception as e:
            ms = (time.time() - t0) * 1000 if 't0' in locals() else 0
            result = _err(HaveIBeenPwnedSource.NAME, e, ms, HaveIBeenPwnedSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result


# ===========================================================================
# CATEGORIA: Clima / Ambiente
# ===========================================================================

class OpenMeteoExtSource:
    NAME = "open_meteo_ext"
    WEIGHT = 0.88
    CATEGORY = "weather"
    REQUIRES_KEY = False
    KEYWORDS = ["clima", "tempo", "temperatura", "chuva", "vento", "umidade",
                 "previsão", "meteorologia"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{OpenMeteoExtSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        try:
            t0 = time.time()
            RateLimiter.wait_if_needed(OpenMeteoExtSource.NAME)
            
            # Geocodifica
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search?"
                f"name={urllib.parse.quote(query)}&count=1&language=pt&format=json"
            )
            geo = _get_with_retry(geo_url, OpenMeteoExtSource.NAME)
            results = geo.get("results", []) if isinstance(geo, dict) else []
            
            if not results:
                ms = (time.time() - t0) * 1000
                result = _err(OpenMeteoExtSource.NAME, "lugar não geocodificado", ms,
                            OpenMeteoExtSource.CATEGORY)
                SourceCache.set(cache_key, result)
                return result
            
            lat, lon = results[0]["latitude"], results[0]["longitude"]
            name = results[0].get("name", query)
            country = results[0].get("country", "")

            # Previsão
            wx_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
                f"&timezone=auto&forecast_days=3"
            )
            wx = _get_with_retry(wx_url, OpenMeteoExtSource.NAME)
            daily = wx.get("daily", {}) if isinstance(wx, dict) else {}
            days = []
            times = daily.get("time", [])
            
            for i, t in enumerate(times[:3]):
                days.append({
                    "date": t,
                    "tmax": (daily.get("temperature_2m_max") or [None])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                    "tmin": (daily.get("temperature_2m_min") or [None])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
                    "precip_mm": (daily.get("precipitation_sum") or [None])[i] if i < len(daily.get("precipitation_sum", [])) else None,
                    "wind_max_kmh": (daily.get("windspeed_10m_max") or [None])[i] if i < len(daily.get("windspeed_10m_max", [])) else None,
                })
            
            ms = (time.time() - t0) * 1000
            result = _ok(OpenMeteoExtSource.NAME, {
                "place": f"{name}, {country}", "lat": lat, "lon": lon, "forecast": days
            }, ms, OpenMeteoExtSource.CATEGORY)
            
            SourceCache.set(cache_key, result)
            return result
            
        except Exception as e:
            ms = (time.time() - t0) * 1000 if 't0' in locals() else 0
            result = _err(OpenMeteoExtSource.NAME, e, ms, OpenMeteoExtSource.CATEGORY)
            SourceCache.set(cache_key, result)
            return result


# ===========================================================================
# CATEGORIA: Educação
# ===========================================================================

class MITOCWSource:
    NAME = "mit_ocw"
    WEIGHT = 0.88
    CATEGORY = "education"
    REQUIRES_KEY = False
    KEYWORDS = ["curso", "aula", "matéria", "universidade", "mit", "educação",
                 "material didático", "lecture", "ensino"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{MITOCWSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://ocw.mit.edu/api/v0/courses/"
            f"?q={urllib.parse.quote(query)}&limit=5"
        )
        data, ms, err = _timed(_get_with_retry, MITOCWSource.NAME, url, source_name=MITOCWSource.NAME)
        
        if err or not data:
            # Fallback: busca no archive
            url2 = (
                f"https://archive.org/advancedsearch.php?"
                f"q=collection:mitocw+{urllib.parse.quote(query)}"
                f"&fl=title,description,year&rows=5&output=json"
            )
            data, ms, err = _timed(_get_with_retry, MITOCWSource.NAME, url2, source_name=MITOCWSource.NAME)
        
        if err or not data:
            result = _err(MITOCWSource.NAME, err, ms, MITOCWSource.CATEGORY)
        else:
            if isinstance(data, dict):
                items = (data.get("response", {}).get("docs", []) or
                         data.get("results", []) or [])
            else:
                items = []
            courses = [
                {"title": i.get("title", ""), "description": (i.get("description") or "")[:200]}
                for i in items[:5]
            ]
            result = _ok(MITOCWSource.NAME, {"courses": courses}, ms, MITOCWSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class KhanAcademySource:
    NAME = "khan_academy"
    WEIGHT = 0.85
    CATEGORY = "education"
    REQUIRES_KEY = False
    KEYWORDS = ["khan academy", "exercício", "matemática", "física", "química",
                 "biologia", "história", "aprendizado", "tutorial"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{KhanAcademySource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://www.khanacademy.org/api/v1/topic/{urllib.parse.quote(query.replace(' ', '-'))}"
        data, ms, err = _timed(_get_with_retry, KhanAcademySource.NAME, url, source_name=KhanAcademySource.NAME)
        
        if err or not data:
            # Alternativa: busca global
            url2 = f"https://www.khanacademy.org/api/v1/search?q={urllib.parse.quote(query)}&lang=pt&limit=5"
            data, ms, err = _timed(_get_with_retry, KhanAcademySource.NAME, url2, source_name=KhanAcademySource.NAME)
        
        if err or not data:
            result = _err(KhanAcademySource.NAME, err, ms, KhanAcademySource.CATEGORY)
        else:
            if isinstance(data, dict):
                results = data.get("results", data.get("content_items", []))
            else:
                results = []
            topics = [
                {"title": r.get("title", r.get("translated_title", "")),
                 "description": (r.get("description") or r.get("translated_description") or "")[:200]}
                for r in (results if isinstance(results, list) else [])[:5]
            ]
            result = _ok(KhanAcademySource.NAME, {"topics": topics}, ms, KhanAcademySource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Astronáutica / Espaço
# ===========================================================================

class SpaceXSource:
    NAME = "spacex"
    WEIGHT = 0.87
    CATEGORY = "space"
    REQUIRES_KEY = False
    KEYWORDS = ["spacex", "foguete", "lançamento", "falcon", "starship",
                 "dragon", "starlink", "elon musk", "missão"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        cache_key = f"{SpaceXSource.NAME}:latest"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = "https://api.spacexdata.com/v5/launches/latest"
        data, ms, err = _timed(_get_with_retry, SpaceXSource.NAME, url, source_name=SpaceXSource.NAME)
        
        if err or not data:
            result = _err(SpaceXSource.NAME, err, ms, SpaceXSource.CATEGORY)
        else:
            result = _ok(SpaceXSource.NAME, {
                "latest_launch": {
                    "name": data.get("name", ""),
                    "date": data.get("date_utc", ""),
                    "success": data.get("success"),
                    "details": (data.get("details") or "")[:300],
                    "rocket": data.get("rocket", ""),
                }
            }, ms, SpaceXSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class APODSource:
    NAME = "nasa_apod"
    WEIGHT = 0.90
    CATEGORY = "space"
    REQUIRES_KEY = False
    KEYWORDS = ["astronomia", "foto espacial", "apod", "nasa", "galáxia", "nebulosa",
                 "planeta", "estrela", "universo", "telescópio"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        cache_key = f"{APODSource.NAME}:today"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY"
        data, ms, err = _timed(_get_with_retry, APODSource.NAME, url, source_name=APODSource.NAME)
        
        if err or not data:
            result = _err(APODSource.NAME, err, ms, APODSource.CATEGORY)
        else:
            result = _ok(APODSource.NAME, {
                "title": data.get("title", ""),
                "date": data.get("date", ""),
                "explanation": (data.get("explanation") or "")[:400],
                "media_type": data.get("media_type", ""),
                "url": data.get("url", ""),
            }, ms, APODSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Wikipedia Multilingue
# ===========================================================================

class WikipediaPTSource:
    NAME = "wikipedia_pt"
    WEIGHT = 0.82
    CATEGORY = "knowledge"
    REQUIRES_KEY = False
    KEYWORDS = ["wikipedia português", "enciclopédia", "definição", "conceito"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{WikipediaPTSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://pt.wikipedia.org/api/rest_v1/page/summary/"
            f"{urllib.parse.quote(query.replace(' ', '_'))}"
        )
        data, ms, err = _timed(_get_with_retry, WikipediaPTSource.NAME, url, source_name=WikipediaPTSource.NAME)
        
        if err or not data:
            result = _err(WikipediaPTSource.NAME, err, ms, WikipediaPTSource.CATEGORY)
        else:
            result = _ok(WikipediaPTSource.NAME, {
                "title": data.get("title", ""),
                "extract": (data.get("extract") or "")[:500],
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }, ms, WikipediaPTSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class WikipediaESSource:
    NAME = "wikipedia_es"
    WEIGHT = 0.75
    CATEGORY = "knowledge"
    REQUIRES_KEY = False
    KEYWORDS = ["espanhol", "español", "wikipedia es"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{WikipediaESSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = (
            f"https://es.wikipedia.org/api/rest_v1/page/summary/"
            f"{urllib.parse.quote(query.replace(' ', '_'))}"
        )
        data, ms, err = _timed(_get_with_retry, WikipediaESSource.NAME, url, source_name=WikipediaESSource.NAME)
        
        if err or not data:
            result = _err(WikipediaESSource.NAME, err, ms, WikipediaESSource.CATEGORY)
        else:
            result = _ok(WikipediaESSource.NAME, {
                "title": data.get("title", ""),
                "extract": (data.get("extract") or "")[:500],
            }, ms, WikipediaESSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# CATEGORIA: Miscellaneous / Utilitários
# ===========================================================================

class NumbersAPISource:
    NAME = "numbers_api"
    WEIGHT = 0.60
    CATEGORY = "misc"
    REQUIRES_KEY = False
    KEYWORDS = ["número", "fato matemático", "trivia", "curiosidade numérica"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{NumbersAPISource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        # Extrai número do query
        nums = re.findall(r"\d+", query)
        n = nums[0] if nums else "42"
        url = f"http://numbersapi.com/{n}/math?json"
        data, ms, err = _timed(_get_with_retry, NumbersAPISource.NAME, url, source_name=NumbersAPISource.NAME)
        
        if err or not data:
            url2 = f"http://numbersapi.com/{n}?json"
            data, ms, err = _timed(_get_with_retry, NumbersAPISource.NAME, url2, source_name=NumbersAPISource.NAME)
        
        if err or not data:
            result = _err(NumbersAPISource.NAME, err, ms, NumbersAPISource.CATEGORY)
        else:
            result = _ok(NumbersAPISource.NAME, {
                "number": n, "text": data.get("text", ""), "type": data.get("type", "")
            }, ms, NumbersAPISource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class QuotableSource:
    NAME = "quotable"
    WEIGHT = 0.65
    CATEGORY = "misc"
    REQUIRES_KEY = False
    KEYWORDS = ["citação", "frase", "quote", "inspiração", "filósofo", "autor"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        cache_key = f"{QuotableSource.NAME}:{query}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.quotable.io/search/quotes?query={urllib.parse.quote(query)}&limit=5"
        data, ms, err = _timed(_get_with_retry, QuotableSource.NAME, url, source_name=QuotableSource.NAME)
        
        if err or not data:
            result = _err(QuotableSource.NAME, err, ms, QuotableSource.CATEGORY)
        else:
            results = data.get("results", []) if isinstance(data, dict) else []
            quotes = [
                {"content": r.get("content", ""), "author": r.get("author", "")}
                for r in results[:5]
            ]
            result = _ok(QuotableSource.NAME, {"quotes": quotes, "total": data.get("totalCount", 0)},
                       ms, QuotableSource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


class DictionaryAPISource:
    NAME = "dictionary_api"
    WEIGHT = 0.78
    CATEGORY = "language"
    REQUIRES_KEY = False
    KEYWORDS = ["dicionário", "definição", "significado", "palavra", "etymology",
                 "sinônimo", "inglês", "dictionary"]

    @staticmethod
    def fetch(query: str) -> ExtSourceResult:
        query = sanitize_query(query)
        word = query.split()[0]  # Pega primeira palavra
        cache_key = f"{DictionaryAPISource.NAME}:{word}"
        
        cached = SourceCache.get(cache_key)
        if cached:
            return cached
        
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
        data, ms, err = _timed(_get_with_retry, DictionaryAPISource.NAME, url, source_name=DictionaryAPISource.NAME)
        
        if err or not data:
            result = _err(DictionaryAPISource.NAME, err, ms, DictionaryAPISource.CATEGORY)
        else:
            entries = data if isinstance(data, list) else []
            definitions = []
            for entry in entries[:2]:
                for meaning in entry.get("meanings", [])[:2]:
                    for defn in meaning.get("definitions", [])[:2]:
                        definitions.append({
                            "pos": meaning.get("partOfSpeech", ""),
                            "definition": defn.get("definition", "")[:300],
                            "example": defn.get("example", ""),
                        })
            result = _ok(DictionaryAPISource.NAME, {
                "word": word,
                "phonetic": entries[0].get("phonetic", "") if entries else "",
                "definitions": definitions[:5],
            }, ms, DictionaryAPISource.CATEGORY)
        
        SourceCache.set(cache_key, result)
        return result


# ===========================================================================
# Registro central — todas as fontes disponíveis
# ===========================================================================

ALL_SOURCES: List[type] = [
    # IA/ML
    HuggingFaceSource,
    HuggingFaceDatasetsSource,
    PapersWithCodeSource,
    # Código
    LibrariesIOSource,
    PyPISource,
    GitLabSource,
    RubyGemsSource,
    NuGetSource,
    SourcegraphSource,
    # Ciência
    DOAJSource,
    CORESource,
    BioRxivSource,
    GBIFSource,
    NASASource,
    # Notícias
    WikinewsSource,
    GDELTSource,
    # Finanças
    FrankfurterSource,
    CoinGeckoExtSource,
    WorldBankSource,
    # Saúde
    OpenFDASource,
    RxNormSource,
    # Geo
    NominatimSource,
    OpenElevationSource,
    IPAPISource,
    RestCountriesSource,
    # Cultura
    MusicBrainzSource,
    TVMazeSource,
    OpenLibraryExtSource,
    WikidataSource,
    GoogleBooksSource,  # Nova fonte adicionada
    # Governança
    DadosAbertosGovBRSource,
    IBGESource,
    ProPublicaCongressSource,
    # Segurança
    CRTShSource,
    ShodanInternetDBSource,
    HaveIBeenPwnedSource,
    # Clima
    OpenMeteoExtSource,
    # Educação
    MITOCWSource,
    KhanAcademySource,
    # Espaço
    SpaceXSource,
    APODSource,
    # Wikipedia multilingue
    WikipediaPTSource,
    WikipediaESSource,
    # Misc
    NumbersAPISource,
    QuotableSource,
    DictionaryAPISource,
]

# Índice por nome
SOURCE_BY_NAME: Dict[str, type] = {s.NAME: s for s in ALL_SOURCES}

# Pesos para integração com SOURCE_WEIGHTS do internet_challenge
EXTENDED_SOURCE_WEIGHTS: Dict[str, float] = {s.NAME: s.WEIGHT for s in ALL_SOURCES}

# Índice de palavras-chave para roteamento por intenção
KEYWORD_INDEX: Dict[str, List[str]] = {}
for _src in ALL_SOURCES:
    for _kw in getattr(_src, "KEYWORDS", []):
        KEYWORD_INDEX.setdefault(_kw.lower(), []).append(_src.NAME)


def get_sources_for_query(query: str, max_sources: int = 5) -> List[str]:
    """
    Retorna os nomes das fontes mais relevantes para uma query,
    baseado em matching de palavras-chave e peso.
    """
    q = query.lower()
    scores: Dict[str, float] = {}
    for kw, source_names in KEYWORD_INDEX.items():
        if kw in q:
            for name in source_names:
                src = SOURCE_BY_NAME.get(name)
                if src:
                    scores[name] = scores.get(name, 0) + src.WEIGHT
    # Ordena por score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in ranked[:max_sources]]


def fetch_extended(source_name: str, query: str) -> Optional[ExtSourceResult]:
    """Executa o fetch de uma fonte pelo nome."""
    src = SOURCE_BY_NAME.get(source_name)
    if not src:
        return None
    try:
        return src.fetch(query)
    except Exception as e:
        logger.error(f"Erro ao executar {source_name}: {e}")
        return ExtSourceResult(
            source=source_name, ok=False,
            details={"error": str(e)},
            category=getattr(src, "CATEGORY", ""),
        )


def fetch_all_relevant(query: str, max_sources: int = 6, timeout_per: int = 10) -> List[ExtSourceResult]:
    """
    Busca em paralelo nas fontes mais relevantes para a query.
    """
    import concurrent.futures
    
    source_names = get_sources_for_query(query, max_sources)
    if not source_names:
        # Fallback: usa as 3 fontes de maior peso
        source_names = sorted(SOURCE_BY_NAME, key=lambda n: SOURCE_BY_NAME[n].WEIGHT, reverse=True)[:3]

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(source_names), 6)) as executor:
        futures = {executor.submit(fetch_extended, name, query): name for name in source_names}
        for future in concurrent.futures.as_completed(futures, timeout=timeout_per * 2):
            try:
                result = future.result(timeout=timeout_per)
                if result:
                    results.append(result)
            except concurrent.futures.TimeoutError:
                name = futures[future]
                results.append(ExtSourceResult(
                    source=name, ok=False,
                    details={"error": "timeout"},
                    category=getattr(SOURCE_BY_NAME.get(name), "CATEGORY", ""),
                ))
            except Exception as e:
                name = futures[future]
                results.append(ExtSourceResult(
                    source=name, ok=False,
                    details={"error": f"erro: {e}"},
                    category=getattr(SOURCE_BY_NAME.get(name), "CATEGORY", ""),
                ))
    return results


def get_health_summary() -> Dict[str, Any]:
    """Retorna um resumo da saúde de todas as fontes"""
    return {
        "total_sources": len(ALL_SOURCES),
        "sources_by_category": defaultdict(list),
        "health_metrics": SourceMetrics.get_health(),
        "unhealthy_sources": SourceMetrics.get_unhealthy_sources(),
        "cache_size": len(SourceCache._cache)
    }


def reset_all_metrics():
    """Reseta todas as métricas e cache"""
    SourceMetrics.reset()
    SourceCache.clear()


# ===========================================================================
# Integrador principal para uso com o sistema ATENA
# ===========================================================================

class ExtendedAtenaIntegrator:
    """Integra as fontes estendidas com o sistema principal da ATENA"""
    
    def __init__(self):
        self.sources = ALL_SOURCES
        self.weights = EXTENDED_SOURCE_WEIGHTS
        self.metrics = SourceMetrics
    
    async def answer_with_extended(self, query: str, user_context: Dict = None) -> Dict:
        """Responde usando combinação de fontes regulares e estendidas"""
        start_time = time.time()
        
        # Pega fontes relevantes
        relevant_sources = get_sources_for_query(query, max_sources=5)
        
        # Busca em paralelo
        results = fetch_all_relevant(query, max_sources=5)
        
        # Agrega resultados por categoria
        aggregated = self._aggregate_by_category(results)
        
        # Gera resposta final
        answer = self._synthesize_response(query, aggregated)
        
        return {
            "answer": answer,
            "sources_used": [r.source for r in results if r.ok],
            "failed_sources": [r.source for r in results if not r.ok],
            "confidence": self._calculate_confidence(results),
            "response_time_ms": (time.time() - start_time) * 1000,
            "metrics": SourceMetrics.get_health(),
            "aggregated_data": aggregated
        }
    
    def _aggregate_by_category(self, results: List[ExtSourceResult]) -> Dict[str, List]:
        """Agrupa resultados por categoria para melhor síntese"""
        grouped = defaultdict(list)
        for r in results:
            if r.ok:
                grouped[r.category].append(r.details)
        return dict(grouped)
    
    def _synthesize_response(self, query: str, aggregated: Dict[str, List]) -> str:
        """Sintetiza uma resposta coerente dos múltiplos resultados"""
        parts = []
        
        for category, items in aggregated.items():
            category_names = {
                "ai_ml": "🤖 Inteligência Artificial",
                "code": "💻 Código e Desenvolvimento",
                "research": "📚 Pesquisa Científica",
                "science": "🔬 Ciência",
                "news": "📰 Notícias",
                "finance": "💰 Finanças",
                "health": "🏥 Saúde",
                "geo": "🌍 Geografia",
                "culture": "🎨 Cultura",
                "knowledge": "📖 Conhecimento",
                "governance": "🏛️ Governança",
                "security": "🔒 Segurança",
                "weather": "🌤️ Clima",
                "education": "🎓 Educação",
                "space": "🚀 Espaço",
                "language": "📝 Idioma",
                "misc": "📌 Diversos"
            }
            
            category_name = category_names.get(category, category.upper())
            parts.append(f"**{category_name}**: {len(items)} {'resultado' if len(items) == 1 else 'resultados'} encontrados")
        
        if not parts:
            return f"Não foram encontradas informações relevantes para '{query}' nas fontes disponíveis."
        
        return f"### Resultados para: {query}\n\n" + "\n".join(parts) + "\n\n💡 Dica: Para mais detalhes, refine sua pesquisa ou use palavras-chave mais específicas."
    
    def _calculate_confidence(self, results: List[ExtSourceResult]) -> float:
        """Calcula nível de confiança baseado nas fontes bem-sucedidas e seus pesos"""
        if not results:
            return 0.0
        
        total_weight = 0.0
        success_weight = 0.0
        
        for r in results:
            weight = self.weights.get(r.source, 0.5)
            total_weight += weight
            if r.ok:
                success_weight += weight
        
        return success_weight / total_weight if total_weight > 0 else 0.0
    
    def get_source_recommendations(self, query: str, min_confidence: float = 0.3) -> List[str]:
        """Recomenda fontes para uma query baseado em histórico de sucesso"""
        recommended = []
        health = SourceMetrics.get_health()
        
        for source_name in get_sources_for_query(query, max_sources=10):
            if source_name in health:
                metrics = health[source_name]
                if metrics["success_rate"] >= min_confidence:
                    recommended.append(source_name)
        
        return recommended[:5]


# Exporta o integrador padrão
default_integrator = ExtendedAtenaIntegrator()
