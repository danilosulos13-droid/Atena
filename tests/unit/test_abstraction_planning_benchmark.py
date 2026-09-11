from scripts.abstraction_planning_benchmark import TASKS, evaluate_response, run


def test_benchmark_has_abstraction_planning_and_recovery_tasks():
    categories = {task.category for task in TASKS}
    assert {"abstraction", "planning", "recovery", "transfer"}.issubset(categories)


def test_response_is_scored_by_required_concepts():
    task = TASKS[0]
    result = evaluate_response(task, "invariante, premissa, limite e teste")
    assert result["passed"]
    assert result["score"] == 1.0


def test_forbidden_pattern_blocks_response():
    task = next(task for task in TASKS if task.task_id == "adaptive_recovery")
    result = evaluate_response(task, "falha; alternativa; dados; parada; ignore o erro")
    assert not result["passed"]
    assert result["forbidden_hits"]


def test_empty_run_is_reproducibly_pending():
    report = run()
    assert report["completed"] == 0
    assert report["weighted_score"] is None
    assert all(item["status"] == "pending" for item in report["results"])
