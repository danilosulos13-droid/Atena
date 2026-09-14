"""Coleta baseada em evidências sobre nanorrobótica.

O módulo consulta apenas fontes públicas em modo somente leitura, normaliza
metadados e trechos, grava proveniência na base SQLite da Atena e produz um
relatório JSON/Markdown. Conteúdo remoto é tratado como dado não confiável:
nunca é executado como código ou instrução.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - diagnostic fallback
    requests = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CONFIG = ROOT / "config" / "nanorobotics_sources.json"
DEFAULT_DB = ROOT / "atena_evolution" / "memory.sqlite3"
DEFAULT_REPORT_DIR = ROOT / "analysis_reports" / "research"
USER_AGENT = "AtenaIA/1.0 (nanorobotics-research; read-only; authorized-project)"
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT = 15


@dataclass(frozen=True)
class Evidence:
    source: str
    source_url: str
    title: str
    url: str
    abstract: str
    published_at: str | None
    authority: str
    weight: float
    query: str

    @property
    def content(self) -> str:
        parts = [self.title, self.abstract]
        return "\n".join(part for part in parts if part).strip()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content"] = self.content
        return payload


def _clean(value: Any, limit: int = 5000) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def _url(value: Any, fallback: str = "") -> str:
    candidate = str(value or fallback).strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return fallback


def _request_json(url: str, *, params: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT) -> Any:
    if requests is None:
        raise RuntimeError("requests não está instalado")
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _request_text(url: str, *, params: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    if requests is None:
        request_url = url
        if params:
            request_url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        request = urllib.request.Request(request_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("resposta excede o limite de tamanho")
        return raw.decode("utf-8", errors="replace")
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/xml"}, timeout=timeout)
    response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("resposta excede o limite de tamanho")
    return response.text


def load_config(path: str | Path = DEFAULT_CONFIG) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("configuração de nanorrobótica deve conter sources como lista")
    result: list[dict[str, Any]] = []
    for source in payload["sources"]:
        if not isinstance(source, dict) or not source.get("enabled", True):
            continue
        url = _url(source.get("url"))
        if not url:
            continue
        item = dict(source)
        item["url"] = url
        item["weight"] = max(0.0, min(1.0, float(item.get("weight", 0.5))))
        result.append(item)
    return result


def _evidence(source: dict[str, Any], query: str, *, title: Any, url: Any = "", abstract: Any = "", published_at: Any = None) -> Evidence:
    source_url = str(source["url"])
    link = _url(url, source_url)
    return Evidence(
        source=str(source.get("name", source_url)),
        source_url=source_url,
        title=_clean(title, 500) or source_url,
        url=link,
        abstract=_clean(abstract),
        published_at=_clean(published_at, 80) or None,
        authority=_clean(source.get("authority", ""), 300),
        weight=float(source.get("weight", 0.5)),
        query=query,
    )


def _crossref(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"query": query, "rows": limit, "select": "DOI,title,URL,published,abstract,container-title"}, timeout=timeout)
    items = []
    for work in (payload.get("message", {}).get("items", []) if isinstance(payload, dict) else []):
        title = (work.get("title") or [""])[0]
        published = work.get("published", {}).get("date-parts", [[None]])[0]
        items.append(_evidence(source, query, title=title, url=work.get("URL") or ("https://doi.org/" + str(work.get("DOI", ""))), abstract=work.get("abstract", ""), published_at="-".join(str(x) for x in published if x)))
    return items


def _openalex(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"search": query, "per-page": limit}, timeout=timeout)
    items = []
    for work in (payload.get("results", []) if isinstance(payload, dict) else []):
        abstract = ""
        inverted = work.get("abstract_inverted_index") or {}
        if isinstance(inverted, dict):
            words = [(pos, word) for word, positions in inverted.items() if isinstance(positions, list) for pos in positions]
            abstract = " ".join(word for _, word in sorted(words))
        items.append(_evidence(source, query, title=work.get("title"), url=work.get("doi") or work.get("id"), abstract=abstract, published_at=work.get("publication_date")))
    return items


def _semantic_scholar(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"query": query, "limit": limit, "fields": "title,abstract,url,year,authors"}, timeout=timeout)
    return [_evidence(source, query, title=item.get("title"), url=item.get("url"), abstract=item.get("abstract"), published_at=item.get("year")) for item in (payload.get("data", []) if isinstance(payload, dict) else [])]


def _europepmc(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"query": query, "format": "json", "pageSize": limit, "resultType": "core"}, timeout=timeout)
    return [_evidence(source, query, title=item.get("title"), url=item.get("doi") and "https://doi.org/" + item["doi"] or "https://europepmc.org/article/" + str(item.get("source", "")) + "/" + str(item.get("id", "")), abstract=item.get("abstractText"), published_at=item.get("firstPublicationDate")) for item in (payload.get("resultList", {}).get("result", []) if isinstance(payload, dict) else [])]


def _pubmed(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    search = _request_json(source["url"], params={"db": "pubmed", "term": query, "retmode": "json", "retmax": limit}, timeout=timeout)
    ids = search.get("esearchresult", {}).get("idlist", []) if isinstance(search, dict) else []
    if not ids:
        return []
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    root = ET.fromstring(_request_text(fetch_url, params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}, timeout=timeout))
    result: list[Evidence] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID", default="")
        title = " ".join(article.findtext(".//ArticleTitle", default="").split())
        abstract = " ".join(" ".join(node.itertext()).strip() for node in article.findall(".//AbstractText"))
        published = article.findtext(".//PubDate/Year") or article.findtext(".//PubDate/MedlineDate")
        if pmid and title:
            result.append(_evidence(source, query, title=title, url="https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/", abstract=abstract, published_at=published))
    return result


def _arxiv(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    xml = _request_text(source["url"], params={"search_query": "all:" + query, "start": 0, "max_results": limit}, timeout=timeout)
    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    result = []
    for entry in root.findall("a:entry", ns):
        result.append(_evidence(source, query, title=entry.findtext("a:title", default="", namespaces=ns), url=entry.findtext("a:id", default="", namespaces=ns), abstract=entry.findtext("a:summary", default="", namespaces=ns), published_at=entry.findtext("a:published", default="", namespaces=ns)))
    return result


def _doaj(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"q": query, "pageSize": limit}, timeout=timeout)
    result = []
    for item in (payload.get("results", []) if isinstance(payload, dict) else []):
        bib = item.get("bibjson", {})
        links = bib.get("link", [])
        link = links[0].get("url") if links and isinstance(links[0], dict) else ""
        result.append(_evidence(source, query, title=bib.get("title"), url=link, abstract=bib.get("abstract"), published_at=bib.get("year")))
    return result


def _zenodo(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    payload = _request_json(source["url"], params={"q": query, "size": limit}, timeout=timeout)
    return [_evidence(source, query, title=item.get("metadata", {}).get("title"), url=item.get("links", {}).get("html"), abstract=item.get("metadata", {}).get("description"), published_at=item.get("metadata", {}).get("publication_date")) for item in (payload.get("hits", {}).get("hits", []) if isinstance(payload, dict) else [])]


def _html_source(query: str, source: dict[str, Any], limit: int, timeout: int) -> list[Evidence]:
    text = _request_text(source["url"], timeout=timeout)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else source.get("name", source["url"])
        body = _clean(soup.get_text(" ", strip=True), 5000)
    except ImportError:
        title, body = str(source.get("name", source["url"])), _clean(text, 5000)
    return [_evidence(source, query, title=title, url=source["url"], abstract=body)] if body else []


ADAPTERS = {
    "crossref": _crossref,
    "openalex": _openalex,
    "semantic_scholar": _semantic_scholar,
    "europepmc": _europepmc,
    "pubmed": _pubmed,
    "arxiv": _arxiv,
    "doaj": _doaj,
    "zenodo": _zenodo,
}


def fetch_source(source: dict[str, Any], query: str, limit: int = 5, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    started = time.monotonic()
    try:
        adapter = ADAPTERS.get(str(source.get("adapter", "")), _html_source)
        items = adapter(query, source, max(1, min(limit, 20)), timeout)
        deduped: list[Evidence] = []
        seen: set[str] = set()
        for item in items:
            key = hashlib.sha256((item.title + "|" + item.url).encode("utf-8")).hexdigest()
            if key not in seen:
                deduped.append(item)
                seen.add(key)
        return {"source": source.get("name", source["url"]), "url": source["url"], "ok": True, "items": [item.to_dict() for item in deduped], "response_time_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:
        return {"source": source.get("name", source["url"]), "url": source["url"], "ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}", "response_time_ms": round((time.monotonic() - started) * 1000, 2)}


def _report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# ATENA — Aprendizagem sobre Nanorrobótica",
        "",
        f"- Consulta: `{payload['query']}`",
        f"- Consultado em: `{payload['started_at']}`",
        f"- Fontes consultadas: **{payload['source_count']}**; respostas OK: **{payload['ok_sources']}**",
        f"- Evidências coletadas: **{len(payload['evidence'])}**",
        "",
        "> Este relatório contém metadados e trechos de fontes públicas. Conteúdo externo é evidência não confiável e não é executado como instrução. A coleta não altera pesos, código ou permissões da Atena.",
        "",
        "## Fontes e evidências",
        "",
    ]
    for index, item in enumerate(payload["evidence"], 1):
        lines.extend([
            f"### {index}. {item['title']}",
            f"- Fonte: **{item['source']}** ([abrir]({item['url']}))",
            f"- Autoridade: {item.get('authority', '')}; peso inicial: {item.get('weight', '')}",
            f"- Publicação: {item.get('published_at') or 'não informado'}",
            f"- Trecho: {item['abstract'][:1200]}",
            "",
        ])
    if payload.get("errors"):
        lines.extend(["## Fontes indisponíveis", ""])
        lines.extend(f"- **{item['source']}**: `{item['error']}`" for item in payload["errors"])
        lines.append("")
    return "\n".join(lines)


def run_learning(*, query: str, config_path: str | Path = DEFAULT_CONFIG, db_path: str | Path = DEFAULT_DB, output_dir: str | Path = DEFAULT_REPORT_DIR, max_sources: int = 20, limit_per_source: int = 5, timeout: int = DEFAULT_TIMEOUT, no_html: bool = False) -> dict[str, Any]:
    from core.knowledge_base import KnowledgeBase

    started = datetime.now(timezone.utc).isoformat()
    sources = load_config(config_path)[:max(1, min(max_sources, 50))]
    results: list[dict[str, Any]] = []
    for source in sources:
        if no_html and source.get("kind") == "html":
            results.append({"source": source.get("name", source["url"]), "url": source["url"], "ok": True, "items": [], "skipped": "html_disabled"})
            continue
        results.append(fetch_source(source, query, limit_per_source, timeout))
        time.sleep(0.05)

    evidence: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for result in results:
        for item in result.get("items", []):
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            evidence.append(item)

    docs = chunks = 0
    with KnowledgeBase(db_path) as kb:
        for item in evidence:
            if len(item.get("abstract", "")) < 40:
                continue
            _, chunk_count, added = kb.add_document(url=item["url"], title=item["title"], topic="nanorobotics", content=item["content"], metadata={"source": item["source"], "source_url": item["source_url"], "authority": item["authority"], "weight": item["weight"], "query": query, "read_only": True})
            if added:
                docs += 1
                chunks += chunk_count
        kb.record_research(query=query, topic="nanorobotics", started_at=started, source_count=len(sources), document_count=docs, chunk_count=chunks, status="completed" if evidence else "no_evidence", summary=f"{len(evidence)} evidências coletadas; {docs} documentos novos; {chunks} trechos indexados.")
        stats = kb.stats()

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload: dict[str, Any] = {"status": "ok" if evidence else "partial", "query": query, "started_at": started, "source_count": len(sources), "ok_sources": sum(1 for item in results if item.get("ok")), "evidence": evidence, "errors": [item for item in results if not item.get("ok")], "documents_added": docs, "chunks_added": chunks, "knowledge_stats": stats}
    json_path = output / f"nanorobotics_learning_{stamp}.json"
    md_path = output / f"nanorobotics_learning_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_report_markdown(payload), encoding="utf-8")
    payload["report_json"] = str(json_path)
    payload["report_markdown"] = str(md_path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coleta e indexa evidências públicas sobre nanorrobótica")
    parser.add_argument("--query", default="nanorobotics nanorobots nanomedicine microrobots")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--max-sources", type=int, default=20)
    parser.add_argument("--limit-per-source", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--no-html", action="store_true")
    args = parser.parse_args(argv)
    payload = run_learning(query=args.query, config_path=args.config, db_path=args.db, output_dir=args.output_dir, max_sources=args.max_sources, limit_per_source=args.limit_per_source, timeout=args.timeout, no_html=args.no_html)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
