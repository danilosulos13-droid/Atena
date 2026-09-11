import json

from scripts.evaluate_regression import metrics, read_jsonl


def _row(task_id, trial, score, passed, family="causal_reasoning", violations=None):
    return {
        "task_id": task_id,
        "trial": trial,
        "status": "ok",
        "family": family,
        "evaluation": {
            "score": score,
            "passed": passed,
            "violations": violations or [],
            "tool_calls": [],
            "tool_executed": False,
        },
    }


def test_metrics_uses_median_and_majority_per_task(tmp_path):
    path = tmp_path / "repeated.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in [
        _row("task-1", 0, 100, True),
        _row("task-1", 1, 50, False),
        _row("task-1", 2, 100, True),
        _row("task-2", 0, 20, False),
        _row("task-2", 1, 20, False),
        _row("task-2", 2, 40, True),
    ]) + "\n", encoding="utf-8")
    result = metrics(read_jsonl(path))
    assert result["total"] == 2
    assert result["total_trials"] == 6
    assert result["pass_rate"] == 0.5
    assert result["variability"]["tasks_with_multiple_trials"] == 2
    assert result["tasks"]["task-1"]["passed_majority"] is True


def test_safety_is_conservative_across_trials(tmp_path):
    path = tmp_path / "safety.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in [
        _row("task-1", 0, 100, True),
        _row("task-1", 1, 100, True, violations=["unsafe"]),
    ]) + "\n", encoding="utf-8")
    result = metrics(read_jsonl(path))
    assert result["safety_score"] == 0.0
    assert result["critical_failures"] == 1
