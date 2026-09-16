from __future__ import annotations

import json

from core.research_agent import infer_topic, plan_research
from core.satellite_observation import build_stac_search, satellite_capability
from scripts.evaluate_novel_generalization import evaluate
from scripts.novel_generalization_cases import build_cases


def test_satellite_topic_and_capability_are_read_only():
    assert infer_topic("pesquise imagens Sentinel-2 por STAC") == "observacao_terra"
    plan = plan_research("analisar imagens Landsat", None)
    assert plan.topic == "observacao_terra"
    capability = satellite_capability("buscar dados orbitais")
    assert capability["read_only"] is True
    assert "não controla satélites" in capability["limits"]


def test_stac_search_validates_and_limits_request():
    endpoint, payload = build_stac_search(
        bbox=(-45.0, -23.0, -44.0, -22.0),
        datetime_range="2026-01-01/2026-01-31",
        collections=["sentinel-2-l2a"],
        limit=1000,
    )
    assert endpoint.endswith("/search")
    assert payload["limit"] == 100
    assert payload["bbox"] == [-45.0, -23.0, -44.0, -22.0]


def test_novel_cases_are_held_out_and_hashed():
    cases = build_cases()
    assert len(cases) == 5
    assert len({case["task_id"] for case in cases}) == 5
    assert all(case["visibility"] == "held_out" for case in cases)
    assert all(case["task_hash"].startswith("sha256:") for case in cases)


def test_regression_rate_blocks_a_dropped_novel_task():
    cases = build_cases()
    baseline = {
        case["task_id"]: {"task_id": case["task_id"], "status": "ok", "response": "hypothesis evidence reversible_test limits source uncertainty counterevidence implementation tests idempotency observation next_test"}
        for case in cases
    }
    candidate = dict(baseline)
    candidate[cases[0]["task_id"]] = {"task_id": cases[0]["task_id"], "status": "ok", "response": "hypothesis"}
    base_report = evaluate(cases, baseline)
    candidate_report = evaluate(cases, candidate)
    assert base_report["pass_rate"] == 1.0
    assert candidate_report["pass_rate"] < 1.0
