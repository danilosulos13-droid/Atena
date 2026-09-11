"""Executor de pesquisa web limitada às fontes RSS configuradas."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.research_sources import fetch_configured_sources


class WebSearchExecutor:
    """Consulta fontes públicas autorizadas sem executar conteúdo externo."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        max_sources: int = 4,
        limit_per_source: int = 5,
        max_items: int = 20,
    ) -> None:
        self.config_path = Path(config_path) if config_path else None
        self.max_sources = max(1, min(max_sources, 10))
        self.limit_per_source = max(1, min(limit_per_source, 20))
        self.max_items = max(1, min(max_items, 50))

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query web vazia")
        domain = str(arguments.get("domain") or "").strip().lower() or None
        kwargs: dict[str, Any] = {
            "query": query,
            "max_sources": self.max_sources,
            "limit_per_source": self.limit_per_source,
            "mode": "autonomous",
        }
        if self.config_path is not None:
            kwargs["config_path"] = self.config_path
        sources = fetch_configured_sources(**kwargs)
        items: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for source in sources:
            if not source.get("ok"):
                errors.append({"source": source.get("source"), "error": source.get("error", "source unavailable")})
                continue
            for item in source.get("items", []):
                url = str(item.get("link") or item.get("url") or "")
                hostname = urlparse(url).netloc.lower()
                if domain and hostname != domain and not hostname.endswith("." + domain):
                    continue
                items.append({
                    "source": source.get("source"),
                    "category": source.get("category"),
                    "title": str(item.get("title", ""))[:500],
                    "url": url[:2000],
                    "summary": str(item.get("summary", ""))[:2000],
                    "published_at": item.get("published_at"),
                    "content_hash": item.get("content_hash"),
                })
                if len(items) >= self.max_items:
                    break
            if len(items) >= self.max_items:
                break
        return {
            "query": query,
            "domain": domain,
            "items": items,
            "errors": errors,
            "source_count": len(sources),
            "network": True,
            "untrusted_content": True,
            "evidence": [item["url"] for item in items if item.get("url")][:10],
        }
