from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "atena_scheduled_cycle.py"
spec = importlib.util.spec_from_file_location("atena_scheduled_cycle_modes", SCRIPT)
assert spec is not None and spec.loader is not None
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)


def test_autonomous_research_does_not_load_extended_sources(monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fontes estendidas não podem ser chamadas no modo autônomo")

    monkeypatch.setattr(cycle, "fetch_configured_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr(cycle, "SOURCE_MODULE_PATH", Path("/definitely/missing/sources.py"))
    monkeypatch.setattr(cycle.importlib.util, "spec_from_file_location", fail_if_called)
    result = cycle.collect_research("deduplicação", "Como detectar memórias repetidas?", mode="autonomous")
    assert result["mode"] == "autonomous"
    assert called is False


def test_interactive_research_can_load_extended_sources(monkeypatch):
    monkeypatch.setattr(cycle, "fetch_configured_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr(cycle, "SOURCE_MODULE_PATH", Path("/definitely/missing/sources.py"))
    result = cycle.collect_research("futebol", "Que dia Santos e Palmeiras jogam?", mode="interactive")
    assert result["mode"] == "interactive"
    assert "módulo de fontes ausente" in result["errors"]
