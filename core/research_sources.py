"""Fontes RSS configuráveis e seguras para a memória da Atena.

O conteúdo externo é tratado como dado não confiável: nunca é executado como
instrução. O adaptador usa apenas HTTP(S), limita tamanho e tempo, deduplica
itens por hash e retorna erros de fonte sem interromper o ciclo.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "research_sources.json"
MAX_BYTES = 2_000_000
DEFAULT_TIMEOUT = 12
USER_AGENT = "AtenaIA/1.0 (authorized-research; contact-project-maintainer)"


@dataclass(frozen=True)
class RSSItem:
    source: str
    category: str
    title: str
    link: str
    published_at: str | None
    summary: str
    content_hash: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: str | None, limit: int = 2000) -> str:
    return " ".join((value or "").split())[:limit]


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_config(path: str | Path = DEFAULT_CONFIG, mode: str = "autonomous") -> list[dict[str, Any]]:
    source_path = Path(path)
    if not source_path.exists():
        return []
    data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("configuração de fontes deve conter sources como lista")
    result = []
    for source in data["sources"]:
        if not isinstance(source, dict) or source.get("type") != "rss" or not source.get("enabled", True):
            continue
        source_mode = str(source.get("mode", "autonomous"))
        if mode != "all" and source_mode != mode:
            continue
        url = str(source.get("url", ""))
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        result.append(source)
    return result


def _fetch_bytes(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("feed excede o limite de tamanho")
    return body


def _find_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names:
            return _clean("".join(child.itertext()))
    return ""


def parse_feed(source: dict[str, Any], body: bytes) -> list[RSSItem]:
    root = ET.fromstring(body)
    source_name = str(source.get("name", source["url"]))
    category = str(source.get("category", "custom"))
    source_url = str(source["url"])
    items: list[RSSItem] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        title = _find_text(element, ("title",))
        summary = _find_text(element, ("description", "summary", "content"))
        published = _find_text(element, ("pubdate", "published", "updated", "date")) or None
        link = _find_text(element, ("link",))
        if not link:
            for child in list(element):
                if child.tag.rsplit("}", 1)[-1].lower() == "link":
                    link = str(child.attrib.get("href", ""))
                    break
        if not title and not link:
            continue
        link = urllib.parse.urljoin(source_url, link)
        item_hash = _hash({"source": source_name, "title": title, "link": link, "published_at": published, "summary": summary})
        items.append(RSSItem(source_name, category, title, link, published, summary, item_hash, source_url))
    return items


def fetch_source(source: dict[str, Any], timeout: int = DEFAULT_TIMEOUT, limit: int = 10) -> dict[str, Any]:
    started = time.monotonic()
    try:
        items = parse_feed(source, _fetch_bytes(str(source["url"]), timeout))
        unique: list[RSSItem] = []
        seen: set[str] = set()
        for item in items:
            if item.content_hash not in seen:
                unique.append(item)
                seen.add(item.content_hash)
            if len(unique) >= limit:
                break
        return {"source": source.get("name", source["url"]), "category": source.get("category", "custom"), "ok": True, "items": [item.to_dict() for item in unique], "response_time_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:
        return {"source": source.get("name", source.get("url", "unknown")), "category": source.get("category", "custom"), "ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}", "response_time_ms": round((time.monotonic() - started) * 1000, 2)}


def select_best_sources(query: str = "", config_path: str | Path = DEFAULT_CONFIG, max_sources: int = 4, mode: str = "autonomous") -> list[dict[str, Any]]:
    query_terms = {term.lower() for term in query.split() if len(term) >= 4}
    sources = load_config(config_path, mode=mode)
    ranked = sorted(
        sources,
        key=lambda source: (
            len(query_terms.intersection({str(x).lower() for x in source.get("keywords", [])})),
            float(source.get("weight", 0.5)),
        ),
        reverse=True,
    )
    return [source for source in ranked[:max_sources]]


def fetch_configured_sources(query: str = "", config_path: str | Path = DEFAULT_CONFIG, max_sources: int = 4, limit_per_source: int = 5, mode: str = "autonomous") -> list[dict[str, Any]]:
    selected = select_best_sources(query=query, config_path=config_path, max_sources=max_sources, mode=mode)
    return [fetch_source(source, limit=limit_per_source) for source in selected]


def fetch_best_sources(query: str = "", config_path: str | Path = DEFAULT_CONFIG, max_sources: int = 4, limit_per_source: int = 5, mode: str = "autonomous") -> list[dict[str, Any]]:
    selected = select_best_sources(query=query, config_path=config_path, max_sources=max_sources, mode=mode)
    return [fetch_source(source, limit=limit_per_source) for source in selected]
