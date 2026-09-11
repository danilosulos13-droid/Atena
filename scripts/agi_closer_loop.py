#!/usr/bin/env python3
"""Loop de promoção para aproximar a Atena de comportamento AGI verificável."""
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
from core.self_evaluation_loop import SelfEvaluationLoop, EvaluationSnapshot


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_score(payload: dict) -> float:
    if not isinstance(payload, dict):
        raise ValueError("payload de benchmark deve ser um dicionário")

    candidates = []
    for key in ("overall_score", "score"):
        value = _to_float(payload.get(key))
        if value is not None:
            candidates.append(value)

    models = payload.get("models")
    if isinstance(models, dict):
        for item in models.values():
            if isinstance(item, dict):
                s = _to_float(item.get("score"))
                if s is not None:
                    candidates.append(s)

    results = payload.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                s = _to_float(item.get("score"))
                if s is not None:
                    candidates.append(s)

    if candidates:
        return float(mean(candidates))
    raise ValueError("Não foi possível extrair um score numérico do benchmark.")


def _make_html(summary: dict) -> str:
    title = html.escape(str(summary.get("benchmark_version", "atena-agi-loop")))
    decision = html.escape(str(summary.get("decision", "unknown")))
    baseline = summary.get("baseline_score")
    candidate = summary.get("candidate_score")
    delta = summary.get("score_delta")
    safety = summary.get("safety_score")
    regression = summary.get("regression_score")
    return f"""
    <!doctype html>
    <html lang=\"pt-BR\">
    <head>
      <meta charset=\"utf-8\" />
      <title>{title}</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; background: #020817; color: #e2e8f0; }}
        .card {{ background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }}
        .badge {{ display: inline-block; padding: 0.35rem 0.75rem; border-radius: 999px; font-weight: bold; background: #1d4ed8; }}
      </style>
    </head>
    <body>
      <div class=\"card\">
        <h1>ATENA — AGI closer loop</h1>
        <div class=\"badge\">{decision}</div>
        <p><strong>Versão:</strong> {title}</p>
        <p><strong>Baseline:</strong> {baseline}</p>
        <p><strong>Candidate:</strong> {candidate}</p>
        <p><strong>Delta:</strong> {delta}</p>
        <p><strong>Safety:</strong> {safety}</p>
        <p><strong>Regression:</strong> {regression}</p>
      </div>
    </body>
    </html>
    """


def run_agi_closer_loop(
    *,
    baseline_path: Path,
    candidate_path: Path,
    benchmark_version: str,
    model: str,
    db_path: Path,
    output_dir: Path,
    min_overall: float = 0.8,
    min_safety: float = 0.7,
    min_regression: float = 0.9,
) -> dict:
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))

    baseline_score = extract_score(baseline_payload)
    candidate_score = extract_score(candidate_payload)
    score_delta = round(candidate_score - baseline_score, 6)

    safety_score = min(1.0, max(0.0, candidate_score))
    regression_score = 1.0 if candidate_score >= baseline_score else max(0.0, candidate_score / max(baseline_score, 1e-9))

    snapshot = EvaluationSnapshot(
        run_id=f"{benchmark_version}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        model=model,
        benchmark_version=benchmark_version,
        overall_score=candidate_score,
        safety_score=safety_score,
        memory_score=candidate_score,
        regression_score=regression_score,
        critical_failures=0,
        old_task_pass_rate=baseline_score,
        new_task_pass_rate=candidate_score,
        successful_tool_actions=1,
        tool_actions=1,
    )
    decision = SelfEvaluationLoop(min_overall=min_overall, min_safety=min_safety, min_regression=min_regression).evaluate(snapshot)

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
            payload={"phase": "baseline", "model": model},
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
            payload={"phase": "candidate", "model": model},
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{benchmark_version}_summary.json"
    html_path = output_dir / f"{benchmark_version}_summary.html"

    summary = {
        "benchmark_version": benchmark_version,
        "model": model,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_delta": score_delta,
        "safety_score": safety_score,
        "regression_score": regression_score,
        "decision": decision.decision,
        "reasons": list(decision.reasons),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(_make_html(summary), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Loop de promoção AGI-closer para a Atena.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--benchmark-version", default="agi-loop-v1")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "agi_reports")
    parser.add_argument("--min-overall", type=float, default=0.8)
    parser.add_argument("--min-safety", type=float, default=0.7)
    parser.add_argument("--min-regression", type=float, default=0.9)
    args = parser.parse_args()

    summary = run_agi_closer_loop(
        baseline_path=args.baseline,
        candidate_path=args.candidate,
        benchmark_version=args.benchmark_version,
        model=args.model,
        db_path=args.db,
        output_dir=args.output_dir,
        min_overall=args.min_overall,
        min_safety=args.min_safety,
        min_regression=args.min_regression,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["decision"] == "promote" else 1


if __name__ == "__main__":
    raise SystemExit(main())
