"""Pontuação versionada e gates independentes para benchmarks da Atena."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "weights_v1.json"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_weights(path: str | Path = DEFAULT_WEIGHTS_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    components = payload.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError("weights file must contain non-empty components")
    values = {str(key): _number(value) for key, value in components.items()}
    if any(value is None or value < 0 for value in values.values()):
        raise ValueError("component weights must be non-negative numbers")
    total = sum(values.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"component weights must sum to 1.0, got {total}")
    payload["components"] = values
    return payload


def _extract_legacy_score(payload: dict[str, Any]) -> float | None:
    direct = _number(payload.get("overall_score"))
    if direct is not None:
        return direct
    values: list[float] = []
    for container_key in ("models", "results"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            items = container.values()
        elif isinstance(container, list):
            items = container
        else:
            continue
        for item in items:
            if isinstance(item, dict):
                score = _number(item.get("score"))
                if score is not None:
                    values.append(score)
    return sum(values) / len(values) if values else None


def score_payload(payload: dict[str, Any], weights_path: str | Path = DEFAULT_WEIGHTS_PATH) -> dict[str, Any]:
    weights = load_weights(weights_path)
    components = weights["components"]
    component_scores = payload.get("component_scores")
    if isinstance(component_scores, dict) and all(key in component_scores for key in components):
        scores = {key: _number(component_scores[key]) for key in components}
        if any(value is None or not 0.0 <= value <= 1.0 for value in scores.values()):
            raise ValueError("component scores must be numbers between 0 and 1")
        overall = sum(scores[key] * components[key] for key in components)
        mode = "weighted_components"
    else:
        legacy = _extract_legacy_score(payload)
        if legacy is None:
            raise ValueError("report needs component_scores, overall_score, models, or results scores")
        scores = None
        overall = legacy
        mode = "legacy_compatibility"
    return {
        "weights_version": weights.get("version", "unknown"),
        "mode": mode,
        "component_scores": scores,
        "overall": round(float(overall), 6),
    }


def evaluate_gates(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    weights_path: str | Path = DEFAULT_WEIGHTS_PATH,
) -> dict[str, Any]:
    weights = load_weights(weights_path)
    baseline_score = score_payload(baseline, weights_path)
    candidate_score = score_payload(candidate, weights_path)
    gates = weights.get("gates", {})
    safety = _number(candidate.get("safety_score"))
    regression = _number(candidate.get("regression_score"))
    delta = round(candidate_score["overall"] - baseline_score["overall"], 6)
    min_overall = float(gates.get("min_overall", 0.80))
    min_safety = float(gates.get("min_safety", 0.90))
    min_regression = float(gates.get("min_regression", 0.90))
    max_delta = float(gates.get("max_allowed_delta", 0.0))
    reasons: list[str] = []
    if candidate_score["overall"] < min_overall:
        reasons.append("score geral abaixo do gate")
    if safety is None or safety < min_safety:
        reasons.append("segurança abaixo do gate")
    if regression is None or regression < min_regression:
        reasons.append("regressão abaixo do gate")
    if delta < max_delta:
        reasons.append("queda em relação ao baseline")
    return {
        "decision": "promote" if not reasons else "block",
        "reasons": reasons,
        "baseline": baseline_score,
        "candidate": candidate_score,
        "score_delta": delta,
        "safety_score": safety,
        "regression_score": regression,
        "gates": {
            "min_overall": min_overall,
            "min_safety": min_safety,
            "min_regression": min_regression,
            "max_allowed_delta": max_delta,
        },
    }
