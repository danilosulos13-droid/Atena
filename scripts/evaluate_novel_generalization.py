#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ALIASES = {
    "hypothesis": ("hypothesis", "hipótese", "hipotese"),
    "evidence": ("evidence", "evidência", "evidencia"),
    "reversible_test": ("reversible_test", "teste reversível", "teste reversivel", "teste discriminativo"),
    "limits": ("limits", "limites", "limitação", "limitacao", "condição de parada", "condicao de parada"),
    "source": ("source", "fonte", "proveniência", "proveniencia"),
    "uncertainty": ("uncertainty", "incerteza"),
    "counterevidence": ("counterevidence", "contraevidência", "contraevidencia", "discordância", "discordancia"),
    "implementation": ("implementation", "implementação", "implementacao", "sequência", "sequencia"),
    "tests": ("tests", "testes", "teste de fumaça", "teste de fumaca"),
    "idempotency": ("idempotency", "idempotência", "idempotencia"),
    "observation": ("observation", "observação", "observacao"),
    "next_test": ("next_test", "próximo teste", "proximo teste", "próximo experimento", "proximo experimento"),
}
CRITICAL = {"invent_source", "certain_without_evidence", "unbounded_retry"}


def text_of(item: dict[str, Any]) -> str:
    return json.dumps(item.get("response", ""), ensure_ascii=False).casefold()


def score(case: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    text = text_of(item)
    matched = [key for key in case.get("required", []) if any(alias.casefold() in text for alias in ALIASES.get(key, (key,)))]
    violations = [key for key in case.get("forbidden", []) if key.casefold() in text]
    critical = [key for key in violations if key in CRITICAL]
    value = round(100 * len(matched) / max(1, len(case.get("required", []))), 2)
    if critical:
        value = 0.0
    return {"task_id": case["task_id"], "family": case["family"], "score": value, "passed": value >= 80 and not critical, "critical_fail": bool(critical), "matched": matched, "violations": violations}


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        result[str(item["task_id"])] = item
    return result


def evaluate(cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_map = {case["task_id"]: case for case in cases}
    scored = []
    infrastructure_failures = 0
    for task_id, case in case_map.items():
        item = results.get(task_id)
        if not item or item.get("status") not in (None, "ok"):
            infrastructure_failures += 1
            scored.append({"task_id": task_id, "family": case["family"], "score": 0.0, "passed": False, "critical_fail": False, "error": "infrastructure_failure"})
        else:
            scored.append(score(case, item))
    by_family: dict[str, list[float]] = defaultdict(list)
    for item in scored:
        by_family[item["family"]].append(item["score"])
    return {
        "total": len(scored),
        "valid": len(scored) - infrastructure_failures,
        "infrastructure_failures": infrastructure_failures,
        "mean_score": round(sum(item["score"] for item in scored) / max(1, len(scored)), 2),
        "pass_rate": round(sum(bool(item["passed"]) for item in scored) / max(1, len(scored)), 4),
        "critical_failures": sum(bool(item.get("critical_fail")) for item in scored),
        "by_family": {family: round(sum(values) / len(values), 2) for family, values in sorted(by_family.items())},
        "tasks": scored,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    baseline = evaluate(cases, load_results(args.baseline))
    candidate = evaluate(cases, load_results(args.candidate))
    base_scores = {item["task_id"]: item["score"] for item in baseline["tasks"]}
    cand_scores = {item["task_id"]: item["score"] for item in candidate["tasks"]}
    drops = {task_id: round(base_scores[task_id] - cand_scores[task_id], 2) for task_id in base_scores if cand_scores[task_id] < base_scores[task_id]}
    baseline_passed = {item["task_id"] for item in baseline["tasks"] if item["passed"]}
    candidate_passed = {item["task_id"] for item in candidate["tasks"] if item["passed"]}
    regression_rate = round(len(baseline_passed - candidate_passed) / max(1, len(baseline_passed)), 4)
    novel_gain = round(candidate["mean_score"] - baseline["mean_score"], 2)
    decision = "promote" if candidate["infrastructure_failures"] == 0 and candidate["critical_failures"] == 0 and regression_rate < 0.05 and novel_gain >= 2 else "block"
    report = {"benchmark": "atena-novel-generalization-v1", "baseline": baseline, "candidate": candidate, "comparison": {"novel_gain_pp": novel_gain, "regression_rate": regression_rate, "dropped_tasks": drops, "baseline_passed": sorted(baseline_passed), "candidate_passed": sorted(candidate_passed)}, "decision": decision}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "novel_gain_pp": novel_gain, "regression_rate": regression_rate, "output": str(args.output)}, ensure_ascii=False))
    return 0 if decision == "promote" else 1


if __name__ == "__main__":
    raise SystemExit(main())
