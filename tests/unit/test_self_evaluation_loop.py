from core.self_evaluation_loop import EvaluationSnapshot, SelfEvaluationLoop


def snapshot(**overrides):
    data = dict(run_id="r1", model="test", benchmark_version="v1", overall_score=.95, safety_score=.90, memory_score=.92, regression_score=.98, old_task_pass_rate=.96, new_task_pass_rate=.90, tasks_completed=9, tasks_total=10)
    data.update(overrides)
    return EvaluationSnapshot(**{key: data[key] for key in EvaluationSnapshot.__dataclass_fields__ if key in data})


def test_promotes_snapshot_above_gates():
    decision = SelfEvaluationLoop().evaluate(snapshot())
    assert decision.decision == "promote"
    assert decision.metrics["tool_success_rate"] == 0.0


def test_blocks_safety_regression_and_critical_failure():
    decision = SelfEvaluationLoop().evaluate(snapshot(safety_score=.70, critical_failures=1, regression_score=.80))
    assert decision.decision == "block"
    assert len(decision.reasons) >= 3


def test_detects_old_task_regression_against_baseline():
    loop = SelfEvaluationLoop()
    decision = loop.evaluate(snapshot(old_task_pass_rate=.80), snapshot(old_task_pass_rate=.96, safety_score=.90))
    assert "queda nas tarefas antigas" in decision.reasons


def test_autonomy_rate_penalizes_intervention_and_unsafe_actions():
    loop = SelfEvaluationLoop()
    safe = loop.autonomy_rate(tasks_completed=9, tasks_total=10, interventions=0, unsafe_actions=0)
    guarded = loop.autonomy_rate(tasks_completed=9, tasks_total=10, interventions=2, unsafe_actions=1)
    assert safe > guarded


def test_incident_id_is_stable():
    loop = SelfEvaluationLoop()
    first = loop.diagnose(component="router", failure="429", hypothesis="quota", evidence_refs=["log://1"])
    second = loop.diagnose(component="router", failure="429", hypothesis="other", evidence_refs=["log://1"])
    assert first.incident_id == second.incident_id
