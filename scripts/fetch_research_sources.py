#!/usr/bin/env python3
"""Coleta RSS e, quando possível, lê o texto completo das páginas vinculadas.

Limites são deliberados: o coletor aceita somente URLs HTTP(S), remove conteúdo
não textual, deduplica por URL e hash do texto, aplica filtros mínimos de
qualidade e não tenta contornar paywalls, robots, autenticação ou bloqueios.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.research_sources import fetch_configured_sources

MEMORY_PATH = ROOT / "atena_evolution" / "learning_memory.jsonl"
USER_AGENT = "AtenaResearchBot/1.0 (+https://github.com/danilosullos-lang/Atena-IA)"
MAX_PAGE_BYTES = 2_000_000
MIN_TEXT_CHARS = 500


class ArticleTextParser(HTMLParser):
    """Extrai texto visível sem executar scripts ou contornar bloqueios."""

    SKIP = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "header", "aside", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.SKIP:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def valid_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def fetch_full_page(url: str, timeout: int) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            return "", "content-type não textual"
        raw = response.read(MAX_PAGE_BYTES + 1)
    if len(raw) > MAX_PAGE_BYTES:
        return "", "página excede limite de 2 MB"
    charset = "utf-8"
    try:
        text = raw.decode(charset, errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    parser = ArticleTextParser()
    parser.feed(text)
    article = html.unescape(parser.text())
    if len(article) < MIN_TEXT_CHARS:
        return "", f"texto insuficiente ({len(article)} caracteres)"
    return article, ""


def enrich(item: dict, result: dict, timeout: int) -> dict:
    url = str(item.get("link") or "").strip()
    title = " ".join(str(item.get("title") or "").split()).strip()
    summary = " ".join(str(item.get("summary") or "").split()).strip()
    output = {
        "url": url,
        "title": title or url,
        "topic": result.get("category", "research"),
        "source_feed": result.get("source", ""),
        "published_at": item.get("published_at"),
        "summary": summary,
        "full_text": "",
        "page_status": "not_requested",
    }
    if not valid_url(url):
        output["page_status"] = "invalid_url"
        return output
    try:
        text, reason = fetch_full_page(url, timeout)
        if text:
            output["full_text"] = text
            output["page_status"] = "full_text"
        else:
            output["page_status"] = reason or "unavailable"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        output["page_status"] = f"unavailable: {type(exc).__name__}"
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-sources", type=int, default=100)
    parser.add_argument("--limit-per-source", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--query", default="")
    parser.add_argument("--no-full-pages", action="store_true")
    args = parser.parse_args()

    results = fetch_configured_sources(
        query=args.query,
        max_sources=max(1, min(args.max_sources, 100)),
        limit_per_source=max(1, min(args.limit_per_source, 10)),
        mode="autonomous",
    )
    candidates: list[tuple[dict, dict]] = []
    seen_urls: set[str] = set()
    for result in results:
        for item in result.get("items", []):
            url = str(item.get("link") or "").strip()
            normalized = url.split("#", 1)[0]
            if not valid_url(normalized) or normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            candidates.append((item, result))
            if len(candidates) >= max(1, min(args.max_pages, 1000)):
                break
        if len(candidates) >= max(1, min(args.max_pages, 1000)):
            break

    if args.no_full_pages:
        enriched = [enrich(item, result, 1) for item, result in candidates]
        for record in enriched:
            record["page_status"] = "not_requested"
            record["full_text"] = ""
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 24))) as pool:
            futures = [pool.submit(enrich, item, result, args.timeout) for item, result in candidates]
            enriched = [future.result() for future in futures]

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    persisted = 0
    full_pages = 0
    rejected = 0
    seen_content: set[str] = set()
    seen_persisted_urls: set[str] = set()
    seen_persisted_hashes: set[str] = set()
    if MEMORY_PATH.exists():
        for line in MEMORY_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                old = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(old, dict):
                old_url = str(old.get("source_url") or "").split("#", 1)[0]
                old_hash = str(old.get("content_hash") or "")
                if old_url:
                    seen_persisted_urls.add(old_url)
                if old_hash:
                    seen_persisted_hashes.add(old_hash)
    with MEMORY_PATH.open("a", encoding="utf-8") as handle:
        for record in enriched:
            text = record["full_text"] or record["summary"]
            if len(text) < MIN_TEXT_CHARS:
                rejected += 1
                continue
            content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
            normalized_url = record["url"].split("#", 1)[0]
            if content_hash in seen_content or content_hash in seen_persisted_hashes or normalized_url in seen_persisted_urls:
                rejected += 1
                continue
            seen_content.add(content_hash)
            seen_persisted_hashes.add(content_hash)
            seen_persisted_urls.add(normalized_url)
            if record["full_text"]:
                full_pages += 1
            handle.write(json.dumps({
                "kind": "internet_research",
                "topic": record["topic"],
                "source_url": record["url"],
                "source_feed": record["source_feed"],
                "title": record["title"],
                "published_at": record["published_at"],
                "content_hash": content_hash,
                "page_status": record["page_status"],
                "payload": {"summary": record["summary"], "full_text": text},
            }, ensure_ascii=False) + "\n")
            persisted += 1

    links = [{"url": x["url"], "title": x["title"], "topic": x["topic"], "page_status": x["page_status"]} for x in enriched if valid_url(x["url"])]
    print(json.dumps({
        "status": "ok",
        "feeds_consulted": len(results),
        "feeds_ok": sum(1 for result in results if result.get("ok")),
        "rss_candidates": len(candidates),
        "article_links": len(links),
        "full_pages_read": full_pages,
        "summaries_or_pages_persisted": persisted,
        "rejected_quality_or_duplicate": rejected,
        "links": links[:100],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
