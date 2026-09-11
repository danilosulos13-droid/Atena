#!/usr/bin/env python3
"""Launcher único para executar o ciclo completo de evolução da Atena."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_command(command: list[str]) -> dict:
    proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa benchmark, análise e promoção da Atena em um único fluxo.")
    parser.add_argument("--baseline", type=Path, default=ROOT / "analysis_reports" / "llama3.2_general_evaluation.json")
    parser.add_argument("--candidate", type=Path, default=ROOT / "analysis_reports" / "general_intelligence_evaluation.json")
    parser.add_argument("--benchmark-version", default="atena-agi-launcher-v1")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "agi_reports")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    parser.add_argument("--min-overall", type=float, default=0.8)
    parser.add_argument("--min-safety", type=float, default=0.7)
    parser.add_argument("--min-regression", type=float, default=0.9)
    args = parser.parse_args()

    steps = [
        [
            sys.executable,
            str(ROOT / "scripts" / "agi_closer_loop.py"),
            "--baseline",
            str(args.baseline),
            "--candidate",
            str(args.candidate),
            "--benchmark-version",
            args.benchmark_version,
            "--model",
            args.model,
            "--db",
            str(args.db),
            "--output-dir",
            str(args.output_dir),
            "--min-overall",
            str(args.min_overall),
            "--min-safety",
            str(args.min_safety),
            "--min-regression",
            str(args.min_regression),
        ]
    ]

    results = []
    for step in steps:
        result = run_command(step)
        results.append(result)
        if result["returncode"] != 0:
            print(json.dumps({"status": "failed", "steps": results}, ensure_ascii=False, indent=2))
            return result["returncode"]

    print(json.dumps({"status": "ok", "steps": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
