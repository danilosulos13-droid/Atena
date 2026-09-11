#!/usr/bin/env python3
"""Avalia automaticamente o desempenho do candidato LoRA antes da notificação.

A avaliação usa o holdout determinístico do dataset SFT, compara o modelo-base
com o adaptador candidato e apenas acrescenta métricas ao relatório do ciclo.
Não promove nem altera o modelo ativo.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.model_candidate_evaluator import build_holdout, evaluate_model, _load_rows


def evaluate_report(report_path: Path) -> dict[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    training = payload.get("training") or {}
    result = training.get("training") or {}
    if result.get("status") != "candidate":
        return {
            "status": "skipped",
            "reason": f"treino não produziu candidato: {result.get('reason', result.get('status', 'desconhecido'))}",
            "examples": int(result.get("examples", 0) or 0),
        }

    model_name = str(result.get("base_model") or payload.get("model") or os.getenv("ATENA_TRAIN_MODEL", "")).strip()
    candidate_path = Path(str(result.get("path", "")))
    if not candidate_path.is_absolute():
        candidate_path = Path.cwd() / candidate_path
    rows = _load_rows(int(os.getenv("ATENA_EVAL_MAX_HOLDOUT", "256")))
    holdout = build_holdout(rows)
    if not model_name:
        return {"status": "blocked", "reason": "modelo-base ausente"}
    if not candidate_path.exists():
        return {"status": "blocked", "reason": f"candidato ausente: {candidate_path}"}
    if len(holdout) < 5:
        return {"status": "skipped", "reason": "holdout insuficiente (mínimo 5 exemplos)", "holdout_examples": len(holdout)}

    max_length = int(os.getenv("ATENA_EVAL_MAX_LENGTH", "512"))
    baseline = evaluate_model(model_name, holdout, max_length=max_length)
    candidate = evaluate_model(model_name, holdout, adapter=str(candidate_path), max_length=max_length)
    improvement = (baseline.loss - candidate.loss) / max(abs(baseline.loss), 1e-9)
    threshold = float(os.getenv("ATENA_MIN_EVAL_IMPROVEMENT", "0.02"))
    status = "pass" if math.isfinite(improvement) and improvement >= threshold else "fail"
    return {
        "status": status,
        "reason": f"melhoria no holdout: {improvement:.2%}; mínimo: {threshold:.2%}",
        "model": model_name,
        "candidate_path": str(candidate_path),
        "holdout_examples": len(holdout),
        "baseline": baseline.__dict__,
        "candidate": candidate.__dict__,
        "improvement": improvement,
        "min_improvement": threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    evaluation = evaluate_report(args.report)
    payload["performance_evaluation"] = evaluation
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))
    return 0 if evaluation["status"] in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
