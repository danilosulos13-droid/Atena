#!/usr/bin/env python3
"""Avalia o checkpoint JSONL usando o contrato Pydantic, não palavras-chave."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.structured_benchmark import StructuredAnswer, evaluate_structured


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = {str(item["task_id"]): item for item in json.loads(args.cases.read_text(encoding="utf-8"))}
    evaluated: list[dict[str, Any]] = []
    for line in args.results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        task_id = str(item.get("task_id"))
        case = cases.get(task_id)
        if case is None:
            evaluated.append({"task_id": task_id, "status": "invalid_case", "score": 0.0})
            continue
        if item.get("status") != "ok":
            evaluated.append({
                "task_id": task_id,
                "family": case.get("family"),
                "status": "infrastructure_error",
                "error_class": item.get("error_class"),
                "error": item.get("error"),
            })
            continue
        try:
            answer = StructuredAnswer.model_validate(item.get("answer", {}))
        except Exception as exc:
            evaluated.append({
                "task_id": task_id,
                "family": case.get("family"),
                "status": "schema_invalid",
                "score": 0.0,
                "error": str(exc),
            })
            continue
        scored = evaluate_structured(case, answer)
        scored["status"] = "valid"
        evaluated.append(scored)

    valid = [item for item in evaluated if item.get("status") == "valid"]
    by_family: dict[str, list[float]] = defaultdict(list)
    for item in valid:
        by_family[str(item.get("family"))].append(float(item["score"]))
    summary = {
        "benchmark": "atena-structured-v2",
        "total_records": len(evaluated),
        "valid_responses": len(valid),
        "schema_invalid": sum(item.get("status") == "schema_invalid" for item in evaluated),
        "infrastructure_failures": sum(item.get("status") == "infrastructure_error" for item in evaluated),
        "mean_score_valid_only": round(sum(item["score"] for item in valid) / len(valid), 2) if valid else None,
        "pass_rate_valid_only": round(sum(bool(item["passed"]) for item in valid) / len(valid), 4) if valid else None,
        "critical_or_policy_violations": sum(bool(item.get("violations")) for item in valid),
        "tool_executions_reported": sum(bool(item.get("tool_executed")) for item in valid),
        "by_family": {family: round(sum(scores) / len(scores), 2) for family, scores in by_family.items()},
    }
    payload = {"summary": summary, "results": evaluated}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["infrastructure_failures"] == 0 and summary["schema_invalid"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
