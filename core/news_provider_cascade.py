"""Fallback resiliente de pesquisa pública: GDELT e Brave, sem depender de HTML de buscadores."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

import requests


TRANSIENT_STATUS = {429, 500, 502, 503, 504}
PERMANENT_STATUS = {401, 402, 403}


@dataclass
class ProviderState:
    failures: int = 0
    opened_until: float = 0.0


class CircuitBreaker:
    def __init__(self, cooldown_seconds: int = 900, failure_threshold: int = 1, clock: Callable[[], float] = time.time):
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = max(1, failure_threshold)
        self.clock = clock
        self.states: dict[str, ProviderState] = {}

    def is_open(self, provider: str) -> bool:
        state = self.states.get(provider)
        if not state:
            return False
        if state.opened_until <= self.clock():
            state.opened_until = 0.0
            state.failures = 0
            return False
        return True

    def record_failure(self, provider: str) -> None:
        state = self.states.setdefault(provider, ProviderState())
        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.opened_until = self.clock() + self.cooldown_seconds

    def record_success(self, provider: str) -> None:
        self.states[provider] = ProviderState()


class SearchProviderCascade:
    """Consulta GDELT primeiro e Brave opcionalmente, sem interromper o RSS."""

    def __init__(
        self,
        *,
        cache_path: str | Path = "atena_evolution/search_provider_cache.json",
        cache_ttl_seconds: int = 1800,
        breaker: CircuitBreaker | None = None,
        session: requests.Session | Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self.cache_path = Path(cache_path)
        self.cache_ttl_seconds = max(0, cache_ttl_seconds)
        self.clock = clock
        self.sleep = sleep
        self.session = session or requests.Session()
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.stats: dict[str, dict[str, int]] = {}

    def _cache_key(self, provider: str, query: str) -> str:
        return f"{provider}:{query.strip().casefold()}"

    def _load_cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def _cache_get(self, provider: str, query: str) -> list[dict[str, Any]] | None:
        entry = self._load_cache().get(self._cache_key(provider, query))
        if not isinstance(entry, dict):
            return None
        if self.clock() - float(entry.get("timestamp", 0)) > self.cache_ttl_seconds:
            return None
        value = entry.get("items")
        return value if isinstance(value, list) else None

    def _cache_put(self, provider: str, query: str, items: list[dict[str, Any]]) -> None:
        data = self._load_cache()
        data[self._cache_key(provider, query)] = {"timestamp": self.clock(), "items": items[:50]}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _record(self, provider: str, key: str, amount: int = 1) -> None:
        state = self.stats.setdefault(provider, {"requests": 0, "success": 0, "rate_limited": 0, "disabled": 0, "errors": 0})
        state[key] = state.get(key, 0) + amount

    @staticmethod
    def _retry_delay(attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 300.0)
        return min(2 ** attempt, 60) + random.uniform(0, 1.5)

    def _request_json(self, provider: str, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        if self.breaker.is_open(provider):
            self._record(provider, "disabled")
            return None

        for attempt in range(3):
            self._record(provider, "requests")
            try:
                response = self.session.get(url, params=params, headers=headers or {}, timeout=(8, 20))
            except requests.RequestException:
                self._record(provider, "errors")
                self.breaker.record_failure(provider)
                return None

            if response.status_code == 200:
                try:
                    payload = response.json()
                except (ValueError, TypeError):
                    self._record(provider, "errors")
                    self.breaker.record_failure(provider)
                    return None
                self.breaker.record_success(provider)
                self._record(provider, "success")
                return payload if isinstance(payload, dict) else None

            if response.status_code in PERMANENT_STATUS:
                self._record(provider, "disabled")
                self.breaker.record_failure(provider)
                return None

            if response.status_code in TRANSIENT_STATUS and attempt < 2:
                if response.status_code == 429:
                    self._record(provider, "rate_limited")
                self.sleep(self._retry_delay(attempt, response.headers.get("Retry-After")))
                continue

            if response.status_code == 429:
                self._record(provider, "rate_limited")
            else:
                self._record(provider, "errors")
            self.breaker.record_failure(provider)
            return None
        return None

    def _gdelt(self, query: str, limit: int) -> list[dict[str, Any]]:
        cached = self._cache_get("gdelt", query)
        if cached is not None:
            return cached[:limit]
        payload = self._request_json(
            "gdelt",
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": query, "mode": "artlist", "maxrecords": min(limit, 50), "format": "json", "sort": "HybridRel"},
        )
        articles = payload.get("articles", []) if payload else []
        items = [
            {"title": str(a.get("title", "")).strip(), "url": str(a.get("url", "")).strip(), "summary": str(a.get("seendate", "")), "source": "GDELT"}
            for a in articles if isinstance(a, dict) and a.get("title") and str(a.get("url", "")).startswith("http")
        ]
        if items:
            self._cache_put("gdelt", query, items)
        return items[:limit]

    def _brave(self, query: str, limit: int) -> list[dict[str, Any]]:
        api_key = os.getenv("ATENA_BRAVE_SEARCH_API_KEY", "").strip()
        if not api_key:
            return []
        cached = self._cache_get("brave", query)
        if cached is not None:
            return cached[:limit]
        payload = self._request_json(
            "brave",
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(limit, 20)},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
        results = payload.get("web", {}).get("results", []) if payload else []
        items = [
            {"title": str(a.get("title", "")).strip(), "url": str(a.get("url", "")).strip(), "summary": str(a.get("description", "")).strip(), "source": "Brave"}
            for a in results if isinstance(a, dict) and a.get("title") and str(a.get("url", "")).startswith("http")
        ]
        if items:
            self._cache_put("brave", query, items)
        return items[:limit]

    def search(self, query: str, *, rss_items: list[dict[str, Any]] | None = None, limit: int = 8, minimum_rss: int = 6) -> list[dict[str, Any]]:
        """Retorna RSS se suficiente; caso contrário tenta GDELT e depois Brave."""
        existing = list(rss_items or [])
        if len(existing) >= minimum_rss:
            return existing

        results = self._gdelt(query, limit)
        if len(results) < limit:
            results.extend(self._brave(query, limit - len(results)))
        seen = {str(item.get("url")) for item in existing}
        for item in results:
            if item.get("url") not in seen:
                existing.append(item)
                seen.add(str(item.get("url")))
            if len(existing) >= limit:
                break
        return existing[:limit]
