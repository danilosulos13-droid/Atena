from pathlib import Path
import json

import core.model_candidate_evaluator as evaluator
from core.model_candidate_evaluator import PromotionResult, build_holdout, promote_candidate


def test_holdout_is_deterministic():
    rows = [{"id": f"id-{i}", "messages": []} for i in range(50)]
    a = [r["id"] for r in build_holdout(rows)]
    b = [r["id"] for r in build_holdout(rows)]
    assert a == b
    assert 5 <= len(a) <= 20


def test_small_dataset_is_blocked():
    assert build_holdout([{"id": str(i), "messages": []} for i in range(4)]) == []


def test_promotion_state_points_to_active_adapter(tmp_path, monkeypatch):
    models = tmp_path / "models"
    candidate = models / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "adapter_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluator, "MODELS", models)
    monkeypatch.setattr(evaluator, "ACTIVE", models / "active")
    monkeypatch.setattr(evaluator, "STATE", tmp_path / "model_promotion_state.json")

    result = PromotionResult("promote", "ok", None, None, 0.5)
    active = promote_candidate(candidate, base_model="base", metrics=result)
    state = json.loads(evaluator.STATE.read_text(encoding="utf-8"))

    assert active == models / "active"
    assert state["evaluation"]["active_path"] == "atena_evolution/models/active"
