from __future__ import annotations

import json

from core.learning_audio import build_learning_spoken_text, latest_learning_spoken_text


def test_spoken_report_includes_research_learning_and_limits() -> None:
    text = build_learning_spoken_text({
        "research_links": [{"url": "https://example.com"}],
        "observations": {
            "research_plan": {"topic": "robótica por Wi-Fi"},
            "insights": [{"text": "protocolos locais reduzem latência", "confidence": 0.8}],
            "risks": ["o modelo do robô ainda não foi confirmado"],
        },
        "training": {"status": "success"},
    })
    assert "robótica por Wi-Fi" in text
    assert "protocolos locais reduzem latência" in text
    assert "ainda não foi confirmado" in text
    assert "consideração final" in text


def test_latest_report_is_loaded(tmp_path) -> None:
    path = tmp_path / "atena_evolution" / "training"
    path.mkdir(parents=True)
    (path / "latest_workflow_result.json").write_text(json.dumps({"training": {"status": "pass"}}), encoding="utf-8")
    text = latest_learning_spoken_text(tmp_path)
    assert "estado do treinamento foi pass" in text
