"""Calcula métricas de autonomia progressiva a partir de um JSON de avaliação."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.self_evaluation_loop import EvaluationSnapshot, SelfEvaluationLoop


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = EvaluationSnapshot(
        run_id=str(data.get("run_id", "unknown")),
        model=str(data.get("model", "unknown")),
        benchmark_version=str(data.get("benchmark_version", "unknown")),
        overall_score=float(data.get("overall_score", 0.0)),
        safety_score=float(data.get("safety_score", 0.0)),
        memory_score=float(data.get("memory_score", 0.0)),
        regression_score=float(data.get("regression_score", 0.0)),
        critical_failures=int(data.get("critical_failures", 0)),
        old_task_pass_rate=float(data.get("old_task_pass_rate", 0.0)),
        new_task_pass_rate=float(data.get("new_task_pass_rate", 0.0)),
        human_interventions=int(data.get("human_interventions", 0)),
        successful_tool_actions=int(data.get("successful_tool_actions", 0)),
        tool_actions=int(data.get("tool_actions", 0)),
    )
    loop = SelfEvaluationLoop()
    decision = loop.evaluate(snapshot)
    output = {"snapshot": data, "decision": decision.to_dict(), "autonomy_rate": loop.autonomy_rate(tasks_completed=int(data.get("tasks_completed", 0)), tasks_total=int(data.get("tasks_total", 0)), interventions=snapshot.human_interventions, unsafe_actions=int(data.get("unsafe_actions", 0)))}
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["decision"]["decision"] == "promote" else 2


if __name__ == "__main__":
    raise SystemExit(main())
