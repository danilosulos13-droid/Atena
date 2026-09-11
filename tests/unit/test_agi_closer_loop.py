import json
from pathlib import Path

from scripts.agi_closer_loop import run_agi_closer_loop


def test_run_agi_closer_loop_builds_promote_summary(tmp_path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output_dir = tmp_path / "agi_loop"
    db = tmp_path / "memory.sqlite3"

    baseline.write_text(json.dumps({"overall_score": 0.78}), encoding="utf-8")
    candidate.write_text(json.dumps({"overall_score": 0.9}), encoding="utf-8")

    summary = run_agi_closer_loop(
        baseline_path=baseline,
        candidate_path=candidate,
        benchmark_version="agi-loop-v1",
        model="llama3.2",
        db_path=db,
        output_dir=output_dir,
        min_overall=0.8,
        min_safety=0.7,
        min_regression=0.9,
    )

    assert summary["decision"] == "promote"
    assert summary["score_delta"] == 0.12
    assert (output_dir / "agi-loop-v1_summary.json").exists()
    assert (output_dir / "agi-loop-v1_summary.html").exists()
