from __future__ import annotations

from core import autonomous_capability_router as router
from core import research_orchestrator
from scripts import atena_scheduled_cycle as cycle


def test_select_capability_routes_math_to_verified_tools():
    decision = router.select_capability(
        "matemática",
        "Calcule uma integral imprópria e prove o resultado usando zeta.",
    )

    assert decision.name == "mathematics"
    assert "direct_public_math_sources" in decision.tools
    assert "mpmath" in decision.tools
    assert decision.confidence >= 0.9


def test_research_for_capability_adapts_math_report(monkeypatch):
    monkeypatch.setattr(
        research_orchestrator,
        "run_deep_research",
        lambda *args, **kwargs: {
            "answer": "I = π^4/15",
            "sources": [{"title": "DLMF", "url": "https://dlmf.nist.gov/25.5", "snippet": "zeta"}],
            "math_verification": {"exact": "π^4/15", "numeric_absolute_error": "1e-50"},
            "json_path": "/tmp/math.json",
            "markdown_path": "/tmp/math.md",
        },
    )

    result = router.research_for_capability("matemática", "Calcule a integral com zeta")

    assert result is not None
    assert result["capability"]["name"] == "mathematics"
    assert result["specialized_metadata"]["exact"] == "π^4/15"
    assert result["sources"][0]["source_url"] == "https://dlmf.nist.gov/25.5"


def test_autonomous_rotation_contains_a_verifiable_math_task():
    topics = [topic for topic, _ in cycle.RESEARCH_TOPICS]
    assert "matemática" in topics
