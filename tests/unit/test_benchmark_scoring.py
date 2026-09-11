from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.benchmark_scoring import evaluate_gates, load_weights, score_payload


WEIGHTS = Path(__file__).resolve().parents[2] / "benchmarks" / "weights_v1.json"


def test_weights_are_versioned_and_sum_to_one() -> None:
    payload = load_weights(WEIGHTS)
    assert payload["version"] == "v1"
    assert sum(payload["components"].values()) == pytest.approx(1.0)


def test_component_score_is_weighted_and_deterministic() -> None:
    result = score_payload(
        {
            "component_scores": {
                "memory": 0.80,
                "planning": 0.80,
                "tool_use": 0.70,
                "causal_reasoning": 0.60,
                "transfer": 0.90,
            }
        },
        WEIGHTS,
    )
    assert result["mode"] == "weighted_components"
    assert result["overall"] == pytest.approx(0.765)


def test_legacy_score_remains_unchanged() -> None:
    result = score_payload({"overall_score": 0.6875576923}, WEIGHTS)
    assert result["mode"] == "legacy_compatibility"
    assert result["overall"] == pytest.approx(0.687558)


def test_safety_and_regression_are_independent_gates() -> None:
    result = evaluate_gates(
        {"overall_score": 0.80},
        {
            "overall_score": 0.90,
            "safety_score": 0.65,
            "regression_score": 0.95,
        },
        WEIGHTS,
    )
    assert result["decision"] == "block"
    assert "segurança abaixo do gate" in result["reasons"]


def test_pipeline_reports_component_scoring(tmp_path: Path) -> None:
    from scripts.evolution_pipeline import run_pipeline

    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"component_scores": {"memory": 0.8, "planning": 0.8, "tool_use": 0.8, "causal_reasoning": 0.8, "transfer": 0.8}, "safety_score": 0.95, "regression_score": 0.95}), encoding="utf-8")
    candidate.write_text(json.dumps({"component_scores": {"memory": 0.9, "planning": 0.85, "tool_use": 0.8, "causal_reasoning": 0.75, "transfer": 0.8}, "safety_score": 0.95, "regression_score": 0.95}), encoding="utf-8")
    summary = run_pipeline(baseline, candidate, "weights-test", "test", tmp_path / "db.sqlite3", tmp_path / "reports", WEIGHTS)
    assert summary["scoring_mode"] == "weighted_components"
    assert summary["weights_version"] == "v1"
    assert summary["gate_evaluation"]["decision"] == "promote"
