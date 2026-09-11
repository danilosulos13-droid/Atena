from pathlib import Path

import requests

from core.news_provider_cascade import CircuitBreaker, SearchProviderCascade


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def gdelt_payload():
    return {"articles": [{"title": "Agentes de IA em segurança", "url": "https://example.org/ai-security", "seendate": "20260827010000"}]}


def test_429_respeita_retry_after_e_tenta_novamente(tmp_path: Path):
    session = FakeSession([
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, gdelt_payload()),
    ])
    sleeps = []
    cascade = SearchProviderCascade(
        cache_path=tmp_path / "cache.json",
        session=session,
        sleep=sleeps.append,
    )

    result = cascade._gdelt("ai safety", 5)

    assert result[0]["url"] == "https://example.org/ai-security"
    assert len(session.calls) == 2
    assert sleeps == [7.0]
    assert cascade.stats["gdelt"]["rate_limited"] == 1


def test_erro_402_abre_circuit_breaker_e_nao_repete_request(tmp_path: Path):
    session = FakeSession([FakeResponse(402)])
    breaker = CircuitBreaker(cooldown_seconds=900)
    cascade = SearchProviderCascade(cache_path=tmp_path / "cache.json", session=session, breaker=breaker)

    assert cascade._gdelt("ai", 5) == []
    assert cascade._gdelt("ai", 5) == []

    assert len(session.calls) == 1
    assert cascade.stats["gdelt"]["disabled"] == 2
    assert breaker.is_open("gdelt") is True


def test_cache_evita_segunda_consulta(tmp_path: Path):
    session = FakeSession([FakeResponse(200, gdelt_payload())])
    cascade = SearchProviderCascade(cache_path=tmp_path / "cache.json", session=session)

    first = cascade._gdelt("ai", 5)
    second = cascade._gdelt("ai", 5)

    assert first == second
    assert len(session.calls) == 1


def test_fallback_brave_quando_gdelt_nao_entrega_resultados(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATENA_BRAVE_SEARCH_API_KEY", "test-key")
    session = FakeSession([
        FakeResponse(503),
        FakeResponse(503),
        FakeResponse(503),
        FakeResponse(200, {"web": {"results": [{"title": "Brave result", "url": "https://example.net/result", "description": "Resumo"}]}}),
    ])
    sleeps = []
    cascade = SearchProviderCascade(cache_path=tmp_path / "cache.json", session=session, sleep=sleeps.append)

    result = cascade.search("ai", rss_items=[], limit=3, minimum_rss=2)

    assert result[0]["source"] == "Brave"
    assert cascade.stats["gdelt"]["errors"] == 1
    assert cascade.stats["brave"]["success"] == 1


def test_rss_suficiente_nao_chama_provedores(tmp_path: Path):
    session = FakeSession([])
    cascade = SearchProviderCascade(cache_path=tmp_path / "cache.json", session=session)
    rss = [{"title": f"Item {i}", "url": f"https://example.org/{i}"} for i in range(6)]

    assert cascade.search("ai", rss_items=rss, limit=8, minimum_rss=6) == rss
    assert session.calls == []
