#!/usr/bin/env python3
"""Pipeline semanal de benchmark rotativo para a Atena."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rotating_benchmark import make_cases


def build_rotation_manifest(*, seed: int, count: int, model: str, output_dir: str | Path) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    cases = make_cases(seed, count)
    cases_path = output_path / f"rotating_cases_seed_{seed}.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "seed": seed,
        "count": count,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_path": str(cases_path),
        "output_dir": str(output_path),
    }
    return manifest


def run_weekly_benchmark(*, seed: int, count: int, model: str, output_dir: str | Path, benchmark_version: str, db_path: str | Path) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest = build_rotation_manifest(seed=seed, count=count, model=model, output_dir=output_path)
    cases_path = Path(manifest["cases_path"])

    report_path = output_path / f"weekly_benchmark_{benchmark_version}_{seed}.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_rotating_regression_benchmark.py"),
            "--seed",
            str(seed),
            "--count",
            str(count),
            "--output",
            str(output_path / f"rotating_results_seed_{seed}.jsonl"),
            "--model",
            model,
        ],
        check=False,
    )

    baseline_path = output_path / f"rotating_results_seed_{seed}.jsonl"
    if not baseline_path.exists():
        raise FileNotFoundError(f"Benchmark não gerou arquivo de resultados: {baseline_path}")

    candidate_path = baseline_path
    summary = {
        "benchmark_version": benchmark_version,
        "seed": seed,
        "count": count,
        "model": model,
        "cases_path": str(cases_path),
        "results_path": str(candidate_path),
        "report_path": str(report_path),
        "manifest": manifest,
        "status": "completed",
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o benchmark semanal rotativo da Atena.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--model", default=os.getenv("ATENA_LOCAL_MODEL", "llama3.2"))
    parser.add_argument("--benchmark-version", default="atena-weekly-v1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "weekly_benchmark")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    args = parser.parse_args()

    summary = run_weekly_benchmark(
        seed=args.seed,
        count=args.count,
        model=args.model,
        output_dir=args.output_dir,
        benchmark_version=args.benchmark_version,
        db_path=args.db,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
