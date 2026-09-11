#!/usr/bin/env python3
"""Dashboard resumido da evolução da Atena."""
from __future__ import annotations

import json
from pathlib import Path


def build_dashboard_summary(report_dir: str | Path) -> dict:
    directory = Path(report_dir)
    files = sorted(directory.glob("**/*.json")) if directory.exists() else []
    latest = None
    for candidate in files:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            latest = payload
            break

    if latest is None:
        return {"status": "ok", "total_reports": 0, "latest_decision": "none", "latest_benchmark": "none"}

    return {
        "status": "ok",
        "total_reports": len(files),
        "latest_decision": str(latest.get("decision", "none")),
        "latest_benchmark": str(latest.get("benchmark_version", candidate.name if 'candidate' in locals() else 'unknown')),
        "candidate_score": latest.get("candidate_score"),
        "baseline_score": latest.get("baseline_score"),
        "score_delta": latest.get("score_delta"),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Mostra o resumo do dashboard de evolução da Atena.")
    parser.add_argument("--report-dir", type=Path, default=Path("atena_evolution"))
    args = parser.parse_args()

    summary = build_dashboard_summary(args.report_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
