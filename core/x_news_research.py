"""Pesquisa controlada de notícias/posts recentes usando a X API oficial."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


class XNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class XPostEvidence:
    post_id: str
    text: str
    url: str
    created_at: str | None
    author_id: str | None
    public_metrics: dict[str, int] | None = None


class XNewsResearch:
    endpoint = "https://api.x.com/2/tweets/search/recent"

    def __init__(self, bearer_token: str | None = None, timeout: int = 20) -> None:
        self.bearer_token = (bearer_token or os.getenv("ATENA_X_BEARER_TOKEN", "")).strip()
        self.timeout = timeout

    def search(self, query: str, max_results: int = 10) -> list[XPostEvidence]:
        if not self.bearer_token:
            raise XNotConfigured("ATENA_X_BEARER_TOKEN não configurado")
        query = " ".join(query.split()).strip()
        if not query:
            raise ValueError("a consulta do X não pode ser vazia")
        max_results = max(10, min(int(max_results), 100))
        response = requests.get(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            params={
                "query": f"{query} -is:retweet lang:pt",
                "max_results": max_results,
                "tweet.fields": "created_at,author_id,public_metrics",
            },
            timeout=self.timeout,
        )
        if response.status_code in {401, 403}:
            raise XNotConfigured("Bearer Token do X inválido ou sem acesso à busca")
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return [
            XPostEvidence(
                post_id=str(item.get("id", "")),
                text=str(item.get("text", "")),
                url=f"https://x.com/i/web/status/{item.get('id', '')}",
                created_at=item.get("created_at"),
                author_id=item.get("author_id"),
                public_metrics=item.get("public_metrics") or {},
            )
            for item in payload.get("data", [])
            if item.get("id") and item.get("text")
        ]
