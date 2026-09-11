from __future__ import annotations

from core.web_research import WebEvidence, _google_search, _tavily_search, build_context
from scripts.atena_telegram_chat import AtenaTelegramChat


def test_current_question_router_detects_santos_palmeiras() -> None:
    assert AtenaTelegramChat.needs_current_web("Que dia o Santos vai jogar contra o Palmeiras?")
    assert AtenaTelegramChat.needs_current_web("Qual é o preço atual do jogo?")
    assert not AtenaTelegramChat.needs_current_web("Explique o que é memória episódica")


def test_web_context_preserves_sources() -> None:
    context = build_context(
        "jogo Santos Palmeiras",
        [WebEvidence("Calendário oficial", "https://example.com/calendar", "Jogo em 26 de agosto")],
    )
    assert "https://example.com/calendar" in context
    assert "Jogo em 26 de agosto" in context


def test_tavily_adapter_normalizes_results(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"title": "Fonte", "url": "https://example.com/a", "content": "Trecho Tavily"}]}

    monkeypatch.setenv("ATENA_TAVILY_API_KEY", "test-key")
    monkeypatch.setattr("core.web_research.requests.post", lambda *args, **kwargs: Response())
    results = _tavily_search("pergunta", 5, 2)
    assert results[0].url == "https://example.com/a"
    assert "Trecho Tavily" in results[0].snippet


def test_google_adapter_normalizes_results(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"title": "Fonte Google", "link": "https://example.com/b", "snippet": "Trecho Google"}]}

    monkeypatch.setenv("ATENA_GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("ATENA_GOOGLE_CSE_ID", "test-cx")
    monkeypatch.setattr("core.web_research.requests.get", lambda *args, **kwargs: Response())
    results = _google_search("pergunta", 5, 2)
    assert results[0].url == "https://example.com/b"
    assert "Trecho Google" in results[0].snippet
