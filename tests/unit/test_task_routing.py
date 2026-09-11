from core.task_routing import provider_order, route_for_task


def test_research_prefers_gemini():
    decision = route_for_task("research")
    assert decision.preferred_provider == "gemini"
    assert provider_order("research", ["local", "anthropic", "gemini"]) == ["gemini", "anthropic", "local"]


def test_code_prefers_anthropic():
    decision = route_for_task("code")
    assert decision.preferred_provider == "anthropic"
    assert provider_order("code", ["local", "gemini", "anthropic"]) == ["anthropic", "gemini", "local"]


def test_private_stays_local_when_available():
    assert provider_order("private", ["gemini", "local"]) == ["local", "gemini"]


def test_unavailable_preferred_provider_falls_back():
    assert provider_order("research", ["local"]) == ["local"]


def test_environment_override(monkeypatch):
    monkeypatch.setenv("ATENA_ROUTE_RESEARCH", "local")
    decision = route_for_task("research")
    assert decision.preferred_provider == "local"
