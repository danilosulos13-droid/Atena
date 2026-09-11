from __future__ import annotations

from core.research_sources import load_config


def test_autonomous_mode_excludes_interactive_club_sources() -> None:
    autonomous = load_config(mode="autonomous")
    names = {item["name"] for item in autonomous}
    assert "Santos FC Oficial" not in names
    assert "Palmeiras Oficial" not in names
    assert "Google News Santos Palmeiras" not in names
    assert "ArXiv Quantum Physics" in names
    assert "Agência Brasil" in names


def test_all_mode_keeps_interactive_sources_available_for_explicit_queries() -> None:
    all_sources = load_config(mode="all")
    names = {item["name"] for item in all_sources}
    assert "Santos FC Oficial" in names
    assert "Palmeiras Oficial" in names
    assert "Google News Santos Palmeiras" in names
