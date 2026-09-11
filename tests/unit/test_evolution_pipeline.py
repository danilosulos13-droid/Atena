import json
from pathlib import Path

from scripts.evolution_pipeline import run_pipeline


def test_run_pipeline_persists_and_reports_progress(tmp_path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output_dir = tmp_path / "reports"
    db = tmp_path / "memory.sqlite3"

    baseline.write_text(json.dumps({"overall_score": 0.7}), encoding="utf-8")
    candidate.write_text(json.dumps({"overall_score": 0.82}), encoding="utf-8")

    summary = run_pipeline(baseline, candidate, "demo-v1", "llama3.2", db, output_dir)

    assert summary["baseline_score"] == 0.7
    assert summary["candidate_score"] == 0.82
    assert summary["delta"] == 0.12
    assert summary["decision"] in {"improved", "stable", "mixed"}
    assert (output_dir / "demo-v1_evolution_summary.json").exists()
    assert (output_dir / "demo-v1_evolution_summary.html").exists()
