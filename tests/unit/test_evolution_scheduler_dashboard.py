from datetime import datetime, timezone

from scripts.atena_evolution_scheduler import build_schedule
from scripts.evolution_dashboard import build_dashboard_summary


def test_build_schedule_returns_interval_and_next_run():
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    schedule = build_schedule(interval_minutes=60, now=now)

    assert schedule["interval_minutes"] == 60
    assert schedule["next_run"] == "2026-09-04T13:00:00Z"
    assert schedule["status"] == "scheduled"


def test_build_dashboard_summary_uses_existing_reports(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "sample.json").write_text(
        '{"benchmark_version": "demo-v1", "decision": "promote", "candidate_score": 0.92, "baseline_score": 0.8, "score_delta": 0.12}',
        encoding="utf-8",
    )

    summary = build_dashboard_summary(report_dir)

    assert summary["status"] == "ok"
    assert summary["total_reports"] == 1
    assert summary["latest_decision"] == "promote"
    assert "demo-v1" in summary["latest_benchmark"]
