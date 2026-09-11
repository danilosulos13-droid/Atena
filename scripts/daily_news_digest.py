"""Gera um briefing diário de notícias com imagens opcionais, sem escrever na memória autônoma."""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import os
import re
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import urljoin

import requests

from core.x_news_research import XNewsResearch, XNotConfigured
from core.monitoring_health import MonitoringHealth
from core.news_provider_cascade import SearchProviderCascade
from core.semantic_dedup import MonitoredItem, SemanticDeduplicator
from core.research_sources import load_config


@dataclass(frozen=True)
class NewsItem:
    category: str
    title: str
    url: str
    source: str
    published: str = ""
    summary: str = ""
    image_url: str = ""


SANTOS_FEEDS: list[tuple[str, str]] = [
    ("Santos FC oficial", "https://www.santosfc.com.br/feed/"),
    ("Gazeta Esportiva Santos", "https://www.gazetaesportiva.com/times/santos/feed/"),
    ("Google News Santos", "https://news.google.com/rss/search?q=Santos+FC+futebol&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
]

FEEDS: dict[str, list[tuple[str, str]]] = {
    "Futebol": [
        ("ge", "https://ge.globo.com/rss/ge/"),
        ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/esportes/feed.xml"),
    ],
    "Jogos e tecnologia": [
        ("Tecnoblog", "https://tecnoblog.net/feed/"),
        ("Canaltech", "https://canaltech.com.br/rss/"),
        ("Olhar Digital", "https://olhardigital.com.br/feed/"),
    ],
    "Política e Brasil": [
        ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
        ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
    ],
    "Mundo": [
        ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
        ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ],
    "Ciência e IA": [
        ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
        ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss.xml"),
    ],
}

SANTOS_TITLE_TERMS = {
    "santos", "santos fc", "peixe", "vila belmiro", "sereias", "sereinhas",
    "santos futebol clube",
}

SANTOS_EXCLUSIONS = {
    "santos dumont", "santos reis", "santos pecadores", "santos nomes",
}

CATEGORY_EXCLUDE_TERMS = {
    "Política e Brasil": {"brasileirão", "futebol", "gol", "gols", "jogo", "jogos", "time", "clube", "campeonato", "torcida"},
}

CATEGORY_REQUIRED_TERMS = {
    "Ciência e IA": {"ciência", "cientista", "pesquisa", "tecnologia", "tecnológico", "ia", "inteligência artificial", "espaço", "saúde", "física", "quântica"},
}


def _category_allowed(item: NewsItem) -> bool:
    title = item.title.casefold()
    excluded = CATEGORY_EXCLUDE_TERMS.get(item.category, set())
    if any(term in title for term in excluded):
        return False
    required = CATEGORY_REQUIRED_TERMS.get(item.category)
    if required and item.source == "Agência Brasil":
        return any(term in title for term in required)
    return True


CATEGORY_PRIORITY = {
    "Santos FC": 0,
    "Futebol": 1,
    "Jogos e tecnologia": 2,
    "Política e Brasil": 3,
    "Mundo": 4,
    "Ciência e IA": 5,
    "Segurança digital": 6,
    "Em alta no X": 7,
}

CONFIG_CATEGORY_MAP = {
    "general_news": "Mundo",
    "official_brazil": "Política e Brasil",
    "economy": "Política e Brasil",
    "economy_official": "Política e Brasil",
    "health": "Política e Brasil",
    "justice_security": "Política e Brasil",
    "environment": "Mundo",
    "agriculture": "Política e Brasil",
    "science_policy": "Ciência e IA",
    "space_science": "Ciência e IA",
    "quantum_technology": "Ciência e IA",
    "artificial_intelligence": "Ciência e IA",
    "machine_learning": "Ciência e IA",
    "language_models": "Ciência e IA",
    "technology": "Jogos e tecnologia",
    "technology_business": "Jogos e tecnologia",
    "technology_gadgets": "Jogos e tecnologia",
    "cybersecurity": "Segurança digital",
    "culture_sports": "Futebol",
}


def _merged_feeds() -> dict[str, list[tuple[str, str]]]:
    """Combina feeds editoriais fixos com o catálogo, sem duplicar URLs."""
    merged = {category: list(sources) for category, sources in FEEDS.items()}
    merged.setdefault("Segurança digital", [])
    known_urls = {url for sources in merged.values() for _, url in sources}
    try:
        configured = load_config(mode="autonomous")
    except Exception:
        configured = []
    for source in configured:
        url = str(source.get("url", ""))
        category = CONFIG_CATEGORY_MAP.get(str(source.get("category", "")))
        name = str(source.get("name", url))
        if not category or not url or url in known_urls:
            continue
        merged.setdefault(category, []).append((name, url))
        known_urls.add(url)
    deduplicated: dict[str, list[tuple[str, str]]] = {}
    seen_urls: set[str] = set()
    for category, sources in merged.items():
        for name, url in sources:
            if url in seen_urls:
                continue
            deduplicated.setdefault(category, []).append((name, url))
            seen_urls.add(url)
    return deduplicated


SOURCE_WEIGHT = {
    "Agência Brasil": 1.00,
    "BBC Brasil": 0.98,
    "MIT Technology Review": 0.96,
    "ge": 0.92,
    "Tecnoblog": 0.88,
    "Canaltech": 0.86,
    "Olhar Digital": 0.86,
    "X": 0.55,
}

DEFAULT_X_TREND_QUERIES: tuple[tuple[str, str], ...] = (
    ("IA", "(\"inteligência artificial\" OR IA OR OpenAI OR Gemini OR ChatGPT)"),
    ("Tecnologia", "(tecnologia OR inovação OR software OR smartphone)"),
    ("Cibersegurança", "(cibersegurança OR cybersecurity OR ransomware OR vulnerabilidade)"),
    ("Brasil e política", "(Brasil OR política OR economia OR Congresso)"),
    ("Esportes", "(futebol OR esporte OR Brasileirão)"),
    ("Jogos", "(jogos OR games OR videogame OR Nintendo OR PlayStation OR Xbox)"),
)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    raw = " ".join("".join(element.itertext()).split())
    return re.sub(r"<[^>]+>", " ", html.unescape(raw)).strip()


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower()) if len(x) > 2}


def _valid_http_url(value: str) -> bool:
    return value.strip().startswith(("http://", "https://"))


def _published_score(value: str) -> float:
    if not value:
        return 0.0
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        age_hours = max(0.0, (dt.datetime.now(dt.timezone.utc) - parsed.astimezone(dt.timezone.utc)).total_seconds() / 3600)
        return max(0.0, 1.0 - min(age_hours, 72.0) / 72.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _clean_summary(value: str, limit: int = 280) -> str:
    value = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    return value[:limit].rstrip(" .") + ("…" if len(value) > limit else "")


_PORTUGUESE_MARKERS = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e", "em",
    "é", "foi", "para", "por", "que", "se", "sem", "uma", "um", "os", "na", "nas",
    "no", "nos", "sobre", "não", "mais", "como", "brasil", "brasileiro", "tecnologia",
}


def _looks_portuguese(text: str) -> bool:
    """Heurística conservadora para evitar enviar texto claramente estrangeiro."""
    normalized = re.sub(r"[^\wÀ-ÿ]+", " ", text.casefold())
    words = set(normalized.split())
    if len(words & _PORTUGUESE_MARKERS) >= 2:
        return True
    return bool(re.search(r"[ãõáéíóúâêôç]", text.casefold()))


def _translate_to_portuguese(text: str, *, timeout: int = 12) -> str:
    """Traduz um campo curto usando endpoint configurável; falha fechada."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean or _looks_portuguese(clean):
        return clean
    endpoint = os.getenv("ATENA_TRANSLATION_ENDPOINT", "https://api.mymemory.translated.net/get")
    response = requests.get(endpoint, params={"q": clean[:1000], "langpair": "auto|pt-BR"}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    translated = str(payload.get("responseData", {}).get("translatedText", "")).strip()
    if not translated or translated.casefold() == clean.casefold() or not _looks_portuguese(translated):
        raise ValueError("tradução para português não confirmada")
    return translated


def normalize_items_to_portuguese(items: Iterable[NewsItem], errors: list[str]) -> list[NewsItem]:
    """Garante que título e resumo enviados sejam portugueses; itens sem tradução são omitidos."""
    if os.getenv("ATENA_TRANSLATION_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        errors.append("tradução desativada; nenhum item estrangeiro é garantido como português")
        return list(items)
    normalized: list[NewsItem] = []
    for item in items:
        try:
            title = _translate_to_portuguese(item.title)
            summary = _translate_to_portuguese(item.summary) if item.summary else ""
            normalized.append(NewsItem(item.category, title[:240], item.url, item.source,
                                      item.published, _clean_summary(summary), item.image_url))
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            errors.append(f"tradução:{item.source}:{type(exc).__name__}")
    return normalized


def _rss_image_url(node: ET.Element, article_url: str) -> str:
    """Extrai imagens de enclosure/media RSS sem confiar em HTML arbitrário."""
    candidates: list[str] = []
    for child in node.iter():
        tag = child.tag.rsplit("}", 1)[-1].lower() if isinstance(child.tag, str) else ""
        if tag in {"content", "thumbnail", "image", "enclosure"}:
            value = child.attrib.get("url") or child.attrib.get("href") or _text(child)
            media_type = child.attrib.get("type", "").lower()
            if value and (not media_type or media_type.startswith("image/")):
                candidates.append(value)
    for candidate in candidates:
        absolute = urljoin(article_url, candidate.strip())
        if _valid_http_url(absolute):
            return absolute
    return ""


def _open_graph_image(article_url: str, timeout: int = 8) -> str:
    """Busca imagem na página final, aceitando redirecionamentos e ordem variável dos metadados."""
    try:
        response = requests.get(
            article_url,
            headers={"User-Agent": "Mozilla/5.0 Atena-IA daily briefing/2.2"},
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", "").lower():
            return ""
        body = response.text[:1_500_000]
        final_url = response.url or article_url
        patterns = (
            r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, body, flags=re.IGNORECASE)
            if match:
                candidate = urljoin(final_url, html.unescape(match.group(1).strip()))
                if _valid_http_url(candidate):
                    return candidate
    except (requests.RequestException, UnicodeError):
        return ""
    return ""


def _download_image(url: str, timeout: int = 20) -> tuple[BytesIO, str] | None:
    """Baixa imagem validando conteúdo antes de enviar ao Telegram."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 Atena-IA Telegram image relay/2.2"},
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        data = response.content
        if not content_type.startswith("image/") or not data or len(data) > 10 * 1024 * 1024:
            return None
        return BytesIO(data), content_type
    except (requests.RequestException, ValueError):
        return None


def resolve_image_url(item: NewsItem, *, allow_open_graph: bool = True) -> str:
    if _valid_http_url(item.image_url):
        return item.image_url
    if allow_open_graph:
        return _open_graph_image(item.url)
    return ""


def fetch_feed(category: str, source: str, url: str, timeout: int = 18) -> list[NewsItem]:
    response = requests.get(url, headers={"User-Agent": "Atena-IA daily briefing/2.1"}, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    nodes = list(root.findall(".//item")) or list(root.findall(".//{*}entry"))
    items: list[NewsItem] = []
    for node in nodes[:30]:
        title = _text(node.find("title"))
        link = _text(node.find("link"))
        if not link:
            link_node = node.find("{*}link")
            link = str(link_node.attrib.get("href", "")) if link_node is not None else ""
        published = _text(node.find("pubDate")) or _text(node.find("{*}published")) or _text(node.find("{*}updated"))
        summary = _text(node.find("description")) or _text(node.find("{*}summary")) or _text(node.find("{*}content"))
        image_url = _rss_image_url(node, link) if link else ""
        if title and _valid_http_url(link):
            items.append(NewsItem(category, title, link, source, published, _clean_summary(summary), image_url))
    return items


def _deduplicate(items: Iterable[NewsItem], *, preserve_categories: bool = False) -> list[NewsItem]:
    result: list[NewsItem] = []
    for item in items:
        title_tokens = _tokens(item.title)
        duplicate = False
        for previous in result:
            if preserve_categories and item.category != previous.category:
                continue
            if item.url == previous.url:
                duplicate = True
                break
            similarity = SequenceMatcher(None, item.title.lower(), previous.title.lower()).ratio()
            overlap = len(title_tokens & _tokens(previous.title)) / max(1, len(title_tokens | _tokens(previous.title)))
            if similarity >= 0.82 or overlap >= 0.72:
                duplicate = True
                break
        if not duplicate:
            result.append(item)
    return result


def _deduplicate_global(items: Iterable[NewsItem]) -> list[NewsItem]:
    """Deduplica entre categorias, priorizando a classificação Santos FC."""
    ordered = sorted(items, key=lambda item: (CATEGORY_PRIORITY.get(item.category, 99), -_rank(item)))
    return _deduplicate(ordered, preserve_categories=False)


def _semantic_news_filter(items: Iterable[NewsItem]) -> list[NewsItem]:
    """Retém notícias novas ou semanticamente alteradas entre ciclos."""
    candidates = list(items)
    try:
        db_path = os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3")
        with SemanticDeduplicator(db_path) as dedup:
            selected: list[NewsItem] = []
            for item in candidates:
                result = dedup.observe(MonitoredItem(
                    kind="news", source=item.source, title=item.title, url=item.url,
                    summary=item.summary, content=f"{item.title}\n{item.summary}",
                    metadata={"category": item.category, "published": item.published},
                ))
                if result.action in {"new", "changed"}:
                    selected.append(item)
            return selected
    except Exception:
        return candidates


def _rank(item: NewsItem, query_terms: set[str] | None = None) -> float:
    terms = query_terms or set()
    relevance = len(_tokens(item.title) & terms) / max(1, len(terms)) if terms else 0.5
    source = SOURCE_WEIGHT.get(item.source, 0.70)
    freshness = _published_score(item.published)
    substance = min(1.0, len(item.summary) / 220.0)
    image_bonus = 0.02 if item.image_url else 0.0
    return 0.40 * freshness + 0.27 * source + 0.20 * relevance + 0.11 * substance + image_bonus


def _health_source_id(source: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", source.casefold()).strip("_")


def collect_rss(limit_per_category: int = 4) -> tuple[list[NewsItem], list[str]]:
    all_items: list[NewsItem] = []
    errors: list[str] = []
    health: MonitoringHealth | None = None
    try:
        health = MonitoringHealth(os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3"))
    except Exception:
        pass
    try:
        for category, sources in _merged_feeds().items():
            category_items: list[NewsItem] = []
            for source, url in sources:
                started = time.monotonic()
                try:
                    found = fetch_feed(category, source, url)
                    category_items.extend(found)
                    if health:
                        health.record_check(_health_source_id(source), status="healthy" if found else "degraded",
                                            latency_ms=(time.monotonic() - started) * 1000, item_count=len(found),
                                            metadata={"category": category, "url": url})
                except Exception as exc:
                    errors.append(f"{source}: {type(exc).__name__}")
                    if health:
                        response = getattr(exc, "response", None)
                        status_code = getattr(response, "status_code", None)
                        health.record_check(_health_source_id(source), status="blocked" if status_code == 403 else "failed",
                                            http_status=status_code, latency_ms=(time.monotonic() - started) * 1000,
                                            error_type=type(exc).__name__, error_message=str(exc),
                                            metadata={"category": category, "url": url})
            category_items = [item for item in category_items if _category_allowed(item)]
            category_items = _deduplicate(category_items)
            category_items.sort(key=lambda item: _rank(item), reverse=True)
            all_items.extend(category_items[: max(1, min(limit_per_category, 8))])
        return _deduplicate_global(all_items), errors
    finally:
        if health:
            health.close()


def collect_public_search_fallback(items: Iterable[NewsItem], limit: int = 8) -> tuple[list[NewsItem], dict]:
    """Completa um RSS insuficiente com GDELT e Brave, sem tornar busca obrigatória."""
    current = list(items)
    query = os.getenv(
        "ATENA_SEARCH_QUERY",
        "latest technology artificial intelligence cybersecurity science",
    )
    cascade = SearchProviderCascade(
        cache_path=os.getenv("ATENA_SEARCH_CACHE_PATH", "atena_evolution/search_provider_cache.json"),
        cache_ttl_seconds=int(os.getenv("ATENA_SEARCH_CACHE_TTL_SECONDS", "1800")),
    )
    payload = cascade.search(
        query,
        rss_items=[{"title": item.title, "url": item.url, "summary": item.summary, "source": item.source} for item in current],
        limit=max(1, min(limit, 20)),
        minimum_rss=int(os.getenv("ATENA_MINIMUM_RSS_ITEMS", "6")),
    )
    known = {item.url for item in current}
    additions = []
    for result in payload:
        url = str(result.get("url", "")).strip()
        title = str(result.get("title", "")).strip()
        if not url or not title or url in known:
            continue
        additions.append(NewsItem(
            "Mundo", title[:240], url, str(result.get("source", "Pesquisa pública")),
            summary=_clean_summary(str(result.get("summary", ""))),
        ))
        known.add(url)
    return current + additions, cascade.stats


def collect_santos_feeds(limit: int = 8) -> tuple[list[NewsItem], list[str]]:
    """Coleta fontes dedicadas e retorna apenas notícias explicitamente do clube."""
    items: list[NewsItem] = []
    errors: list[str] = []
    health: MonitoringHealth | None = None
    try:
        health = MonitoringHealth(os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3"))
    except Exception:
        pass
    try:
        for source, url in SANTOS_FEEDS:
            started = time.monotonic()
            try:
                found = fetch_feed("Santos FC", source, url)
                items.extend(found)
                if health:
                    health.record_check(_health_source_id(source), status="healthy" if found else "degraded",
                                        latency_ms=(time.monotonic() - started) * 1000, item_count=len(found),
                                        metadata={"category": "Santos FC", "url": url})
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__}")
                if health:
                    response = getattr(exc, "response", None)
                    status_code = getattr(response, "status_code", None)
                    health.record_check(_health_source_id(source), status="blocked" if status_code == 403 else "failed",
                                        http_status=status_code, latency_ms=(time.monotonic() - started) * 1000,
                                        error_type=type(exc).__name__, error_message=str(exc),
                                        metadata={"category": "Santos FC", "url": url})
        selected = [item for item in items if _is_santos_news(item)]
        selected = _deduplicate(selected)
        selected.sort(key=lambda item: _rank(item), reverse=True)
        return selected[: max(1, min(limit, 8))], errors
    finally:
        if health:
            health.close()


def _is_santos_news(item: NewsItem) -> bool:
    """Exige sinal explícito no título para evitar confundir cidade ou outro assunto."""
    title = re.sub(r"\s+", " ", item.title.lower()).strip()
    if any(exclusion in title for exclusion in SANTOS_EXCLUSIONS):
        return False
    return any(term in title for term in SANTOS_TITLE_TERMS)


def collect_santos(items: Iterable[NewsItem], limit: int = 3) -> list[NewsItem]:
    """Seleciona somente matérias cujo título identifica claramente o Santos FC."""
    trusted = {"ge", "Agência Brasil", "BBC Brasil", "Santos FC oficial", "Google News Santos"}
    selected: list[NewsItem] = []
    for item in items:
        if _is_santos_news(item) and item.source in trusted:
            selected.append(NewsItem(
                "Santos FC", item.title, item.url, item.source,
                item.published, item.summary, item.image_url,
            ))
    unique = _deduplicate(selected)
    return sorted(unique, key=lambda item: _rank(item), reverse=True)[:max(1, min(limit, 5))]


def _x_trend_queries() -> list[tuple[str, str]]:
    configured = os.getenv("ATENA_X_TREND_QUERIES", "").strip()
    if not configured:
        return list(DEFAULT_X_TREND_QUERIES)
    queries: list[tuple[str, str]] = []
    for raw in configured.split("||"):
        value = raw.strip()
        if not value:
            continue
        if "=" in value:
            label, query = value.split("=", 1)
            queries.append((label.strip()[:40] or "Tema", query.strip()))
        else:
            queries.append((value[:40], value))
    return queries or list(DEFAULT_X_TREND_QUERIES)


def collect_x(query: str | None = None, limit: int = 10) -> list[NewsItem]:
    """Agrega sinais de múltiplos temas do X e ranqueia por engajamento e recência."""
    researcher = XNewsResearch()
    query_sets = [("Consulta personalizada", query)] if query else _x_trend_queries()
    posts_by_id = {}
    labels_by_id: dict[str, str] = {}
    try:
        for label, trend_query in query_sets:
            for post in researcher.search(trend_query, max(10, min(limit, 20))):
                if post.post_id:
                    posts_by_id[post.post_id] = post
                    labels_by_id[post.post_id] = label
    except (XNotConfigured, requests.RequestException):
        # O X é opcional: token ausente, plano sem acesso ou indisponibilidade
        # não podem interromper o briefing RSS nem provocar tentativas repetidas.
        return []

    def score(post) -> float:
        metrics = post.public_metrics or {}
        likes = int(metrics.get("like_count", 0))
        reposts = int(metrics.get("retweet_count", 0))
        replies = int(metrics.get("reply_count", 0))
        return 1.0 * likes + 2.5 * reposts + 1.5 * replies + 100.0 * _published_score(post.created_at or "")

    ranked = sorted(posts_by_id.values(), key=score, reverse=True)[:max(1, min(limit, 20))]
    return [
        NewsItem(
            "Em alta no X",
            " ".join(post.text.split())[:220],
            post.url,
            "X",
            post.created_at or "",
            f"Tema monitorado: {labels_by_id.get(post.post_id, 'geral')}. Sinal de interesse público; confirme na fonte original.",
        )
        for post in ranked
    ]


def _why_it_matters(category: str) -> str:
    return {
        "Futebol": "impacto esportivo",
        "Santos FC": "informação principal para a torcida santista",
        "Jogos e tecnologia": "produto, mercado ou tecnologia",
        "Política e Brasil": "impacto público no Brasil",
        "Mundo": "repercussão internacional",
        "Ciência e IA": "avanço científico ou tecnológico",
        "Em alta no X": "sinal de interesse; requer confirmação",
    }.get(category, "relevância geral")


def _published_label(value: str) -> str:
    if not value:
        return "horário não informado"
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        local = parsed.astimezone(dt.timezone(dt.timedelta(hours=-3)))
        return local.strftime("%d/%m às %H:%M")
    except (TypeError, ValueError, OverflowError):
        return "horário não informado"


def _caption(item: NewsItem) -> str:
    prefix = "Santos FC | torcida santista" if item.category == "Santos FC" else item.category
    published = _published_label(item.published)
    return (
        f"<b>{html.escape(prefix)} — {html.escape(item.title[:220])}</b>\n"
        f"<i>Fonte: {html.escape(item.source)} | Publicado: {published}</i>\n"
        f"<i>{html.escape(item.summary[:420] or 'Resumo indisponível; consulte a fonte original.')}</i>\n"
        f"<u>Por que importa:</u> {html.escape(_why_it_matters(item.category))}.\n"
        f"<a href=\"{html.escape(item.url, quote=True)}\">Ler fonte original</a>"
    )


def format_digest(items: Iterable[NewsItem], errors: list[str], *, include_x: bool, max_items_per_category: int = 3) -> str:
    now = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=-3)))
    grouped: dict[str, list[NewsItem]] = {}
    for item in _semantic_news_filter(_deduplicate_global(items)):
        grouped.setdefault(item.category, []).append(item)
    for category in grouped:
        grouped[category] = sorted(grouped[category], key=lambda item: _rank(item), reverse=True)[:max_items_per_category]
    lines = [
        "ATENA — principais notícias do dia | briefing editorial",
        f"Atualizado: {now.strftime('%d/%m/%Y às %H:%M')} (horário de Brasília)",
        "",
        "Seleção por atualidade, relevância, confiabilidade e diversidade de fontes.",
        "Cada título abre a matéria original; imagens acompanham a notícia quando validadas.",
        "",
    ]
    for category, category_items in grouped.items():
        lines.append(f"<b>{html.escape(category)}</b>")
        for item in category_items:
            title = html.escape(item.title[:210])
            source = html.escape(item.source)
            published = html.escape(_published_label(item.published))
            lines.append(f"• <a href=\"{html.escape(item.url, quote=True)}\"><b>{title}</b></a>")
            lines.append(f"  <i>Fonte: {source} | Publicado: {published}</i>")
            if item.summary:
                lines.append(f"  {html.escape(item.summary[:230])}")
            lines.append(f"  <u>Relevância:</u> {html.escape(_why_it_matters(category))}.")
        lines.append("")
    if include_x and not grouped.get("Em alta no X"):
        lines.extend(["<b>Em alta no X</b>", "Nenhum resultado disponível; o token pode não estar configurado.", ""])
    if errors:
        visible_errors = "; ".join(errors[:5])
        suffix = "…" if len(errors) > 5 else ""
        lines.extend([f"<b>Fontes indisponíveis neste ciclo ({len(errors)}):</b> {html.escape(visible_errors + suffix)}", "Será feita nova tentativa no próximo briefing.", ""])
    return "\n".join(lines)[:3900]


def _telegram_credentials() -> tuple[str, str]:
    token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("ATENA_TELEGRAM_BOT_TOKEN e ATENA_TELEGRAM_CHAT_ID são obrigatórios")
    return token, chat_id


def send_telegram(message: str) -> None:
    token, chat_id = _telegram_credentials()
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()


def send_telegram_news(items: Iterable[NewsItem], errors: list[str], *, include_x: bool, max_items_per_category: int = 3) -> tuple[int, int]:
    """Envia uma foto por notícia quando possível; cai para texto sem interromper o lote."""
    token, chat_id = _telegram_credentials()
    selected: list[NewsItem] = []
    grouped: dict[str, list[NewsItem]] = {}
    for item in _deduplicate_global(items):
        grouped.setdefault(item.category, []).append(item)
    for category, category_items in grouped.items():
        selected.extend(sorted(category_items, key=lambda item: _rank(item), reverse=True)[:max_items_per_category])

    header = format_digest([], errors, include_x=include_x, max_items_per_category=max_items_per_category)
    send_telegram(header)
    sent_photos = 0
    sent_text = 0
    for item in selected:
        image_url = resolve_image_url(item)
        if image_url:
            # Matérias do Santos frequentemente usam URLs intermediárias do Google News
            # ou bloqueiam o fetch do Telegram; nesse caso retransmitimos bytes validados.
            downloaded = _download_image(image_url) if item.category == "Santos FC" else None
            if downloaded:
                image_file, content_type = downloaded
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": _caption(item), "parse_mode": "HTML"},
                    files={"photo": ("santos-news.jpg", image_file, content_type)},
                    timeout=30,
                )
            else:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    json={"chat_id": chat_id, "photo": image_url, "caption": _caption(item), "parse_mode": "HTML"},
                    timeout=25,
                )
            if response.ok:
                sent_photos += 1
                continue
        send_telegram(_caption(item))
        sent_text += 1
    return sent_photos, sent_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-x", action="store_true")
    parser.add_argument("--items-per-category", type=int, default=3)
    parser.add_argument("--no-images", action="store_true", help="Enviar somente texto")
    parser.add_argument("--no-santos", action="store_true", help="Não incluir a seção Santos FC")
    args = parser.parse_args()
    items, errors = collect_rss(limit_per_category=max(1, min(args.items_per_category, 8)))
    if os.getenv("ATENA_ENABLE_SEARCH_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}:
        items, fallback_stats = collect_public_search_fallback(items, limit=max(4, args.items_per_category * 3))
        if fallback_stats:
            errors.extend(
                f"search:{provider}:{metrics.get('rate_limited', 0)} rate-limits, {metrics.get('errors', 0)} errors"
                for provider, metrics in fallback_stats.items()
                if metrics.get("rate_limited", 0) or metrics.get("errors", 0)
            )
    if not args.no_santos:
        santos_items, santos_errors = collect_santos_feeds(limit=max(6, args.items_per_category * 2))
        errors.extend(santos_errors)
        items.extend(santos_items)
        items.extend(collect_santos(items, limit=args.items_per_category))
    items = _deduplicate_global(items)
    include_x = args.include_x and bool(os.getenv("ATENA_X_BEARER_TOKEN", "").strip())
    if include_x:
        items.extend(collect_x())
    items = normalize_items_to_portuguese(items, errors)
    items = _deduplicate_global(items)
    message = format_digest(items, errors, include_x=include_x, max_items_per_category=args.items_per_category)
    if args.dry_run:
        print(message)
    elif args.no_images:
        send_telegram(message)
        print(f"Briefing diário enviado com {len(items)} itens e {len(errors)} erros de fonte.")
    else:
        photos, text_fallbacks = send_telegram_news(items, errors, include_x=include_x, max_items_per_category=args.items_per_category)
        print(f"Briefing diário enviado com {len(items)} itens, {photos} imagens e {text_fallbacks} fallbacks de texto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
