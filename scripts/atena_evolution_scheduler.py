#!/usr/bin/env python3
"""Agendador mínimo do ciclo de evolução da Atena."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_schedule(*, interval_minutes: int = 60, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    next_run = current + timedelta(minutes=interval_minutes)
    return {
        "interval_minutes": int(interval_minutes),
        "current_time": current.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "next_run": next_run.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "scheduled",
    }


def run_schedule(*, interval_minutes: int = 60, baseline: Path | str | None = None, candidate: Path | str | None = None,
                 benchmark_version: str = "scheduled-cycle-v1", model: str = "llama3.2", output_dir: Path | str | None = None,
                 db: Path | str | None = None) -> dict:
    schedule = build_schedule(interval_minutes=interval_minutes)
    baseline_path = Path(baseline) if baseline else ROOT / "analysis_reports" / "llama3.2_general_evaluation.json"
    candidate_path = Path(candidate) if candidate else ROOT / "analysis_reports" / "general_intelligence_evaluation.json"
    out_dir = Path(output_dir) if output_dir else ROOT / "atena_evolution" / "scheduler_reports"
    db_path = Path(db) if db else ROOT / "atena_evolution" / "memory.sqlite3"

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "atena_agi_launcher.py"),
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--benchmark-version",
            benchmark_version,
            "--model",
            model,
            "--output-dir",
            str(out_dir),
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    payload = {
        "schedule": schedule,
        "benchmark_version": benchmark_version,
        "model": model,
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "atena_agi_launcher.py"),
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--benchmark-version",
            benchmark_version,
            "--model",
            model,
            "--output-dir",
            str(out_dir),
            "--db",
            str(db_path),
        ],
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Agenda e executa o ciclo de evolução da Atena.")
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--baseline", type=Path, default=ROOT / "analysis_reports" / "llama3.2_general_evaluation.json")
    parser.add_argument("--candidate", type=Path, default=ROOT / "analysis_reports" / "general_intelligence_evaluation.json")
    parser.add_argument("--benchmark-version", default="scheduled-cycle-v1")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "scheduler_reports")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    args = parser.parse_args()

    result = run_schedule(
        interval_minutes=args.interval_minutes,
        baseline=args.baseline,
        candidate=args.candidate,
        benchmark_version=args.benchmark_version,
        model=args.model,
        output_dir=args.output_dir,
        db=args.db,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
