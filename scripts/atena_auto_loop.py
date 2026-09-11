#!/usr/bin/env python3
"""Loop automático de evolução da Atena em background."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.research_sources import fetch_best_sources


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _persist_best_sources(query: str, max_sources: int = 3) -> dict:
    digest = fetch_best_sources(query=query, max_sources=max_sources, limit_per_source=3, mode="autonomous")
    path = ROOT / "atena_evolution" / "autonomous_research_digest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"query": query, "selected_at": _ts(), "sources": digest}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def run_once(*, benchmark_version: str, model: str, output_dir: Path, db: Path) -> dict:
    research_digest = _persist_best_sources(
        "AI AGI evolution benchmarking safety autonomous improvement learning",
        max_sources=3,
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "atena_daily_cycle.py"),
            "--benchmark-version",
            benchmark_version,
            "--model",
            model,
            "--output-dir",
            str(output_dir),
            "--db",
            str(db),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    payload = {
        "timestamp": _ts(),
        "benchmark_version": benchmark_version,
        "model": model,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    log_path = ROOT / "atena_evolution" / "automation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(str(payload) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Mantém o ciclo de evolução da Atena executando em loop automático.")
    parser.add_argument("--interval-seconds", type=int, default=int(os.getenv("ATENA_AUTO_INTERVAL_SECONDS", "86400")))
    parser.add_argument("--benchmark-version", default=os.getenv("ATENA_AUTO_BENCHMARK_VERSION", "atena-auto-v1"))
    parser.add_argument("--model", default=os.getenv("ATENA_LOCAL_MODEL", "llama3.2"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "daily_runs")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    args = parser.parse_args()

    interval = max(60, args.interval_seconds)
    print(f"[atena-auto-loop] starting interval={interval}s version={args.benchmark_version}")
    while True:
        result = run_once(
            benchmark_version=args.benchmark_version,
            model=args.model,
            output_dir=args.output_dir,
            db=args.db,
        )
        if result["returncode"] == 0:
            print(f"[atena-auto-loop] success {result['timestamp']}")
        else:
            print(f"[atena-auto-loop] blocked {result['timestamp']} returncode={result['returncode']}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
