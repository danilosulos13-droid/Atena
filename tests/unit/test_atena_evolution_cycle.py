import json
from pathlib import Path

from scripts.atena_evolution_cycle import run_evolution_cycle


def test_run_evolution_cycle_generates_report_and_decision(tmp_path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output_dir = tmp_path / "reports"
    db = tmp_path / "memory.sqlite3"

    baseline.write_text(json.dumps({"overall_score": 0.8}), encoding="utf-8")
    candidate.write_text(json.dumps({"overall_score": 0.92}), encoding="utf-8")

    summary = run_evolution_cycle(
        baseline_path=baseline,
        candidate_path=candidate,
        benchmark_version="evo-cycle-v1",
        model="llama3.2",
        db_path=db,
        output_dir=output_dir,
        min_overall=0.8,
        min_safety=0.7,
        min_regression=0.9,
    )

    assert summary["decision"] == "promote"
    assert summary["score_delta"] == 0.12
    assert (output_dir / "evo-cycle-v1_summary.json").exists()
    assert (output_dir / "evo-cycle-v1_summary.html").exists()
