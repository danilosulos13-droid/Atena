#!/usr/bin/env python3
"""Pipeline mínimo de evolução da ATENA com benchmark, baseline e relatório."""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.learning_progress import LearningProgress
from core.benchmark_scoring import DEFAULT_WEIGHTS_PATH, evaluate_gates, score_payload


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_score(payload: dict) -> float:
    if isinstance(payload, dict):
        score = _to_float(payload.get("overall_score"))
        if score is not None:
            return score

        models = payload.get("models")
        if isinstance(models, dict):
            values = []
            for item in models.values():
                if isinstance(item, dict):
                    s = _to_float(item.get("score"))
                    if s is not None:
                        values.append(s)
            if values:
                return float(mean(values))

        results = payload.get("results")
        if isinstance(results, list):
            values = []
            for item in results:
                if isinstance(item, dict):
                    s = _to_float(item.get("score"))
                    if s is not None:
                        values.append(s)
            if values:
                return float(mean(values))

    raise ValueError("Não foi possível extrair um score numérico do relatório de benchmark.")


def build_summary(report: dict, benchmark_version: str, model: str) -> dict:
    return {
        "benchmark_version": benchmark_version,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_score": report.get("baseline_score"),
        "candidate_score": report.get("candidate_score"),
        "delta": report.get("delta"),
        "decision": report.get("decision"),
        "weights_version": report.get("weights_version"),
        "scoring_mode": report.get("scoring_mode"),
        "gate_evaluation": report.get("gate_evaluation"),
    }


def write_html(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    title = html.escape(summary["benchmark_version"])
    body = f"""
    <!doctype html>
    <html lang=\"pt-BR\">
    <head>
      <meta charset=\"utf-8\" />
      <title>{title}</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
        .card {{ background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }}
        .tag {{ display: inline-block; background: #1d4ed8; padding: 0.35rem 0.7rem; border-radius: 999px; font-weight: bold; }}
        h1 {{ margin-top: 0; }}
        code {{ background: #0b1120; padding: 0.2rem 0.45rem; border-radius: 6px; }}
      </style>
    </head>
    <body>
      <div class=\"card\">
        <h1>ATENA — evolução de benchmark</h1>
        <div class=\"tag\">{html.escape(str(summary.get('decision', 'unknown')))}</div>
        <p><strong>Benchmark:</strong> <code>{title}</code></p>
        <p><strong>Modelo:</strong> <code>{html.escape(str(summary.get('model', 'unknown')))}</code></p>
        <p><strong>Baseline:</strong> {summary.get('baseline_score', 'n/a')}</p>
        <p><strong>Candidate:</strong> {summary.get('candidate_score', 'n/a')}</p>
        <p><strong>Delta:</strong> {summary.get('delta', 'n/a')}</p>
      </div>
    </body>
    </html>
    """
    path.write_text(body, encoding="utf-8")


def run_pipeline(
    baseline_path: Path,
    candidate_path: Path,
    benchmark_version: str,
    model: str,
    db_path: Path,
    output_dir: Path,
    weights_path: Path = DEFAULT_WEIGHTS_PATH,
) -> dict:
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    baseline_scoring = score_payload(baseline_payload, weights_path)
    candidate_scoring = score_payload(candidate_payload, weights_path)
    baseline_score = baseline_scoring["overall"]
    candidate_score = candidate_scoring["overall"]
    delta = round(candidate_score - baseline_score, 6)
    gate_evaluation = evaluate_gates(baseline_payload, candidate_payload, weights_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with LearningProgress(db_path) as progress:
        progress.record_cycle(
            cycle_id=f"{benchmark_version}-baseline",
            model=model,
            benchmark_version=benchmark_version,
            benchmark_score=baseline_score,
            evidence_count=1,
            validated_lesson_count=0,
            lessons_consulted_count=0,
            regression_status="pass",
            payload={"phase": "baseline", "source_file": str(baseline_path)},
        )
        progress.record_cycle(
            cycle_id=f"{benchmark_version}-candidate",
            model=model,
            benchmark_version=benchmark_version,
            benchmark_score=candidate_score,
            evidence_count=1,
            validated_lesson_count=0,
            lessons_consulted_count=0,
            regression_status="pass",
            payload={"phase": "candidate", "source_file": str(candidate_path)},
        )
        trend = progress.benchmark_summary(benchmark_version)

    summary = build_summary({
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "delta": delta,
        "decision": trend.get("decision", "stable"),
        "weights_version": baseline_scoring["weights_version"],
        "scoring_mode": candidate_scoring["mode"],
        "gate_evaluation": gate_evaluation,
    }, benchmark_version, model)
    summary["baseline_scoring"] = baseline_scoring
    summary["candidate_scoring"] = candidate_scoring
    summary["trend"] = trend
    summary["helper_files"] = []

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{benchmark_version}_evolution_summary.json"
    html_path = output_dir / f"{benchmark_version}_evolution_summary.html"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_html(html_path, summary)

    def _display_path(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    summary["helper_files"] = [_display_path(json_path), _display_path(html_path)]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o pipeline de evolução do benchmark da ATENA.")
    parser.add_argument("--baseline", type=Path, required=True, help="Relatório JSON do baseline.")
    parser.add_argument("--candidate", type=Path, required=True, help="Relatório JSON do candidato.")
    parser.add_argument("--benchmark-version", default="atena-benchmark-v1")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "evolution_reports")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS_PATH, help="Arquivo versionado de pesos.")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    summary = run_pipeline(args.baseline, args.candidate, args.benchmark_version, args.model, args.db, args.output_dir, args.weights)
    print(json.dumps({
        "benchmark_version": args.benchmark_version,
        "model": args.model,
        "baseline_score": summary["baseline_score"],
        "candidate_score": summary["candidate_score"],
        "delta": summary["delta"],
        "decision": summary["decision"],
        "helper_files": summary["helper_files"],
    }, ensure_ascii=False, indent=2))

    if args.fail_on_regression and summary.get("decision") == "regressed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
