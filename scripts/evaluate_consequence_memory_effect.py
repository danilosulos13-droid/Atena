#!/usr/bin/env python3
"""Compara a mesma bateria de tarefas com e sem lições da memória.

Os arquivos de entrada são JSONL; cada linha precisa conter task_id e um
outcome/status. O script não executa ferramentas nem altera memória produtiva.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

SUCCESS = {"success", "passed", "pass", "ok"}
REGRESSION = {"failure", "failed", "error", "blocked", "timeout", "invalid"}


def load(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido em {path}:{number}: {exc}") from exc
        task_id = record.get("task_id") or record.get("case_id")
        if not task_id:
            raise ValueError(f"{path}:{number} não contém task_id/case_id")
        if task_id in records:
            raise ValueError(f"task_id duplicado em {path}: {task_id}")
        records[str(task_id)] = record
    return records


def outcome(record: dict[str, Any]) -> str:
    value = record.get("outcome") or record.get("status") or record.get("result")
    if isinstance(value, dict):
        value = value.get("outcome") or value.get("status")
    return str(value or "unknown").casefold()


def is_success(record: dict[str, Any]) -> bool:
    return outcome(record) in SUCCESS


def is_regression(record: dict[str, Any]) -> bool:
    return outcome(record) in REGRESSION or record.get("critical_failure") is True


def bootstrap(values: list[float], samples: int, seed: int) -> tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        means.append(statistics.fmean(rng.choice(values) for _ in values))
    means.sort()
    return (means[int(samples * 0.025)], statistics.fmean(values), means[int(samples * 0.975)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-memory", type=Path, required=True)
    ap.add_argument("--without-memory", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=8132026)
    ap.add_argument("--bootstrap-samples", type=int, default=2000)
    args = ap.parse_args()

    enabled = load(args.with_memory)
    disabled = load(args.without_memory)
    common = sorted(set(enabled) & set(disabled))
    if not common:
        raise SystemExit("nenhuma tarefa pareada encontrada")

    pairs = []
    for task_id in common:
        a, b = enabled[task_id], disabled[task_id]
        pairs.append({
            "task_id": task_id,
            "with_memory": {"outcome": outcome(a), "success": is_success(a), "regression": is_regression(a)},
            "without_memory": {"outcome": outcome(b), "success": is_success(b), "regression": is_regression(b)},
            "delta": int(is_success(a)) - int(is_success(b)),
        })

    n = len(pairs)
    enabled_success = sum(x["with_memory"]["success"] for x in pairs)
    disabled_success = sum(x["without_memory"]["success"] for x in pairs)
    enabled_reg = sum(x["with_memory"]["regression"] for x in pairs)
    disabled_reg = sum(x["without_memory"]["regression"] for x in pairs)
    deltas = [float(x["delta"]) for x in pairs]
    improved = sum(x["delta"] > 0 for x in pairs)
    worsened = sum(x["delta"] < 0 for x in pairs)
    ties = n - improved - worsened
    delta_ci = bootstrap(deltas, max(100, args.bootstrap_samples), args.seed)

    report = {
        "schema_version": 1,
        "decision": "promote_memory" if delta_ci[0] > 0 and enabled_reg <= disabled_reg else "hold",
        "paired_tasks": n,
        "metrics": {
            "with_memory": {
                "successes": enabled_success,
                "success_rate": enabled_success / n,
                "regressions": enabled_reg,
                "regression_rate": enabled_reg / n,
            },
            "without_memory": {
                "successes": disabled_success,
                "success_rate": disabled_success / n,
                "regressions": disabled_reg,
                "regression_rate": disabled_reg / n,
            },
            "absolute_success_uplift": (enabled_success - disabled_success) / n,
            "improved_tasks": improved,
            "worsened_tasks": worsened,
            "ties": ties,
            "bootstrap_delta_95ci": {"lower": delta_ci[0], "mean": delta_ci[1], "upper": delta_ci[2]},
        },
        "pairs": pairs,
        "policy": {
            "requires_positive_lower_ci": True,
            "regression_must_not_increase": True,
            "no_side_effects_executed_by_evaluator": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "paired_tasks": n, "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["decision"] == "promote_memory" else 2


if __name__ == "__main__":
    raise SystemExit(main())
