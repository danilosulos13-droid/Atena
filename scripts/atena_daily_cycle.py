#!/usr/bin/env python3
"""Ciclo diário automatizado de evolução da Atena."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_daily_cycle(*, baseline: str | Path | None = None, candidate: str | Path | None = None,
                   benchmark_version: str = "daily-cycle-v1", model: str = "llama3.2",
                   output_dir: str | Path | None = None, db: str | Path | None = None) -> dict:
    baseline_path = Path(baseline) if baseline else ROOT / "analysis_reports" / "llama3.2_general_evaluation.json"
    candidate_path = Path(candidate) if candidate else ROOT / "analysis_reports" / "general_intelligence_evaluation.json"
    out_dir = Path(output_dir) if output_dir else ROOT / "atena_evolution" / "daily_runs"
    db_path = Path(db) if db else ROOT / "atena_evolution" / "memory.sqlite3"
    run_id = f"{benchmark_version}-{_timestamp()}"
    cycle_dir = out_dir / run_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    command = [
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
        str(cycle_dir),
        "--db",
        str(db_path),
    ]

    proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
    stdout_payload = proc.stdout.strip()
    stderr_payload = proc.stderr.strip()
    parsed = {}
    if stdout_payload:
        try:
            parsed = json.loads(stdout_payload)
        except json.JSONDecodeError:
            parsed = {"raw_output": stdout_payload}

    payload = {
        "run_id": run_id,
        "benchmark_version": benchmark_version,
        "model": model,
        "status": "ok" if proc.returncode == 0 else "blocked",
        "returncode": proc.returncode,
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "report_dir": str(cycle_dir),
        "stdout": stdout_payload,
        "stderr": stderr_payload,
        "details": parsed,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    latest_path = ROOT / "atena_evolution" / "daily_cycle_latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o ciclo diário automático de evolução da Atena.")
    parser.add_argument("--baseline", type=Path, default=ROOT / "analysis_reports" / "llama3.2_general_evaluation.json")
    parser.add_argument("--candidate", type=Path, default=ROOT / "analysis_reports" / "general_intelligence_evaluation.json")
    parser.add_argument("--benchmark-version", default="daily-cycle-v1")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "daily_runs")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    args = parser.parse_args()

    payload = run_daily_cycle(
        baseline=args.baseline,
        candidate=args.candidate,
        benchmark_version=args.benchmark_version,
        model=args.model,
        output_dir=args.output_dir,
        db=args.db,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
