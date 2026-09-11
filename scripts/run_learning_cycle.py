#!/usr/bin/env python3
"""Grava um snapshot de benchmark da Atena e calcula o trend longitudinal."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.learning_progress import LearningProgress


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_score(payload: dict, selected_model: str | None = None) -> tuple[float, dict]:
    if payload.get("overall_score") is not None:
        score = _safe_float(payload["overall_score"])
        if score is not None:
            return score, {"source": "overall_score"}

    models = payload.get("models")
    if isinstance(models, dict):
        if selected_model:
            model_payload = models.get(selected_model)
            if isinstance(model_payload, dict) and model_payload.get("score") is not None:
                score = _safe_float(model_payload["score"])
                if score is not None:
                    return score, {"source": "model", "selected_model": selected_model}
        candidate_scores = []
        for item in models.values():
            if isinstance(item, dict) and item.get("score") is not None:
                s = _safe_float(item["score"])
                if s is not None:
                    candidate_scores.append(s)
        if candidate_scores:
            return float(mean(candidate_scores)), {"source": "model_average", "models": len(candidate_scores)}

    results = payload.get("results")
    if isinstance(results, list):
        scores = []
        for item in results:
            if isinstance(item, dict) and item.get("score") is not None:
                s = _safe_float(item["score"])
                if s is not None:
                    scores.append(s)
        if scores:
            return float(mean(scores)), {"source": "result_average", "tasks": len(scores)}

    raise ValueError("Não foi possível extrair um score numérico do benchmark informado.")


def _extract_evidence_count(payload: dict) -> int:
    if isinstance(payload.get("results"), list):
        return len(payload["results"])
    if isinstance(payload.get("models"), dict):
        total = 0
        for item in payload["models"].values():
            if isinstance(item, dict):
                total += int(item.get("total", 0) or 0)
        if total:
            return total
    return 1


def _build_cycle_id(prefix: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix or 'benchmark'}-{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Registra um snapshot benchmark da Atena para evolução longitudinal.")
    parser.add_argument("--input", type=Path, required=True, help="Arquivo JSON do benchmark a registrar.")
    parser.add_argument("--benchmark-version", default="atena-benchmark-v1", help="Versão do benchmark.")
    parser.add_argument("--model", default="unknown", help="Modelo ou alvo da execução.")
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution" / "memory.sqlite3", help="Banco SQLite de progresso.")
    parser.add_argument("--cycle-id", default=None, help="Identificador manual do ciclo.")
    parser.add_argument("--fail-on-regression", action="store_true", help="Retorna código 1 se a tendência for regressiva.")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Arquivo de benchmark não encontrado: {args.input}")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    score, score_meta = _extract_score(payload, args.model if args.model != "unknown" else None)
    cycle_id = args.cycle_id or _build_cycle_id(args.benchmark_version.replace(" ", "-").lower())
    evidence_count = _extract_evidence_count(payload)

    db_path = args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with LearningProgress(db_path) as progress:
        trend = progress.benchmark_summary(args.benchmark_version)
        regression_status = "pass" if trend.get("decision") in {"improved", "stable", "mixed", "insufficient_data"} else "fail"
        progress.record_cycle(
            cycle_id=cycle_id,
            model=args.model,
            benchmark_version=args.benchmark_version,
            benchmark_score=score,
            evidence_count=evidence_count,
            validated_lesson_count=0,
            lessons_consulted_count=0,
            success_rate=None,
            regression_status=regression_status,
            payload={
                "prompt_version": payload.get("benchmark") or args.benchmark_version,
                "input_file": str(args.input),
                "score_source": score_meta,
                "task_count": evidence_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        final_trend = progress.benchmark_summary(args.benchmark_version)

    print(json.dumps({
        "cycle_id": cycle_id,
        "benchmark_version": args.benchmark_version,
        "model": args.model,
        "score": round(score, 6),
        "trend": final_trend,
    }, ensure_ascii=False, indent=2))

    if args.fail_on_regression and final_trend.get("decision") in {"regressed"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
