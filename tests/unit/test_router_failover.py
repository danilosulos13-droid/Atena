import asyncio

from core.atena_llm_router import (
    AtenaLLMRouterAdvanced,
    LLMResponse,
    ProviderStatus,
    ProviderMetrics,
    RouterConfig,
)


class FakeProvider:
    def __init__(self, name: str, failure: Exception | None = None):
        self.name = name
        self.metrics = ProviderMetrics()
        self.failure = failure
        self.calls = 0

    async def execute_with_monitoring(self, request):
        self.calls += 1
        if self.failure:
            error, self.failure = self.failure, None
            raise error
        return LLMResponse("resposta de fallback", self.name, "fake", 0, tokens_used=4)


def test_router_fails_over_after_quota_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_PROVIDER_QUOTA_DB", str(tmp_path / "quota.sqlite3"))
    monkeypatch.setenv("ATENA_SEMANTIC_CACHE", "0")
    router = AtenaLLMRouterAdvanced(RouterConfig(semantic_cache_enabled=False))
    gemini = FakeProvider("gemini", RuntimeError("HTTP 429 quota exceeded"))
    local = FakeProvider("local")
    router._providers = {"gemini": gemini, "local": local}
    router.health_checker._status = {
        "gemini": ProviderStatus.HEALTHY,
        "local": ProviderStatus.HEALTHY,
    }

    response = asyncio.run(router.generate("pesquise notícias", task_type="research"))

    assert response.provider == "local"
    assert gemini.calls == 1
    assert local.calls == 1
    assert not router.quota_ledger.available("gemini")
