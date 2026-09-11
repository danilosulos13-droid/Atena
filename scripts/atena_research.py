#!/usr/bin/env python3
"""Motor de pesquisa geral da Atena: busca -> coleta -> deduplica -> indexa.

Uso:
  python scripts/atena_research.py "responsabilidade civil no Brasil"
  python scripts/atena_research.py --topic direito "LGPD e tratamento de dados"
  python scripts/atena_research.py --stats
  python scripts/atena_research.py --search "responsabilidade civil"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.knowledge_base import KnowledgeBase
from core.web_research import search_web

DB = Path(__import__('os').getenv("ATENA_MEMORY_DB", str(ROOT / "atena_evolution" / "memory.sqlite3")))
UA = "Atena-IA knowledge research/1.0"

LEGAL_DOMAINS = ("planalto.gov.br", "stf.jus.br", "stj.jus.br", "trf", "tst.jus.br", "tse.jus.br", "cnj.jus.br", "gov.br")

def expand_query(topic: str, query: str) -> list[str]:
    base = query.strip()
    if not base:
        return []
    qs = [base]
    if topic.casefold() in {"direito", "advocacia", "jurídico", "juridico"}:
        qs += [f"{base} legislação jurisprudência Brasil", f"{base} site:gov.br OR site:stj.jus.br OR site:stf.jus.br"]
    qs.append(f"{base} fontes oficiais")
    return list(dict.fromkeys(qs))


def fetch_page(url: str, timeout: int = 20, max_chars: int = 200_000) -> tuple[str, str]:
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    if "text/html" not in ctype and "text/plain" not in ctype and "xml" not in ctype:
        return "", r.url
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else r.url
    text = soup.get_text(" ", strip=True)
    return (f"{title}\n{text}"[:max_chars], r.url)


def research(topic: str, query: str, limit: int = 12) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    candidates = []
    for q in expand_query(topic, query):
        candidates.extend(search_web(q, limit=min(8, limit), timeout=15))
    seen = set()
    unique = []
    for item in candidates:
        if item.url in seen:
            continue
        seen.add(item.url)
        unique.append(item)
        if len(unique) >= limit:
            break
    docs = chunks = fetched = 0
    errors = []
    with KnowledgeBase(DB) as kb:
        for item in unique:
            try:
                content, final_url = fetch_page(item.url)
                if len(content) < 200:
                    content = f"{item.title}\n{item.snippet}"
                doc_id, chunk_count, added = kb.add_document(
                    url=final_url, title=item.title, topic=topic,
                    content=content,
                    metadata={"query": query, "snippet": item.snippet, "researched_at": started},
                )
                fetched += 1
                if added:
                    docs += 1
                    chunks += chunk_count
            except Exception as exc:
                errors.append({"url": item.url, "error": f"{type(exc).__name__}: {exc}"})
        rid = kb.record_research(query=query, topic=topic, started_at=started, source_count=len(unique), document_count=docs, chunk_count=chunks, status="completed" if unique else "failed", summary=f"Coletadas {docs} páginas novas; {chunks} trechos indexados.")
        stats = kb.stats()
    return {"research_id": rid, "topic": topic, "query": query, "sources_found": len(unique), "documents_added": docs, "chunks_added": chunks, "errors": errors[:10], "stats": stats}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="?")
    p.add_argument("--topic", default="geral")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--stats", action="store_true")
    p.add_argument("--search")
    args = p.parse_args()
    if args.stats:
        with KnowledgeBase(DB) as kb:
            print(json.dumps(kb.stats(), ensure_ascii=False, indent=2))
        return 0
    if args.search:
        with KnowledgeBase(DB) as kb:
            print(json.dumps(kb.search(args.search, limit=20), ensure_ascii=False, indent=2))
        return 0
    if not args.query:
        p.error("informe uma pergunta/assunto ou use --stats/--search")
    print(json.dumps(research(args.topic, args.query, max(1, min(args.limit, 30))), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
