import pytest

from core.agent_plan_loop import Plan, PlanStep, PlannerExecutorCritic, ToolRegistry, ToolSpec, plan_fingerprint


def test_safe_plan_executes_and_critic_accepts():
    registry = ToolRegistry()
    registry.register(ToolSpec("read_status", lambda params: {"status": "ok", "evidence": ["status://local"]}))
    loop = PlannerExecutorCritic(registry)
    plan = Plan("consultar status", (PlanStep("s1", "consultar", "read_status", success_criteria=("evidence",)),))
    result = loop.execute(plan)
    assert result["critic"]["accepted"]
    assert result["observations"][0]["status"] == "ok"
    assert plan_fingerprint(plan)


def test_sensitive_plan_waits_for_approval():
    registry = ToolRegistry()
    registry.register(ToolSpec("send_message", lambda params: {"sent": True}, risk="high", requires_approval=True))
    loop = PlannerExecutorCritic(registry)
    plan = Plan("enviar mensagem", (PlanStep("s1", "enviar", "send_message", requires_approval=True),))
    result = loop.execute(plan)
    assert result["observations"][0]["status"] == "awaiting_approval"
    assert not result["critic"]["accepted"]


def test_failed_step_runs_registered_rollback():
    calls = []
    registry = ToolRegistry()
    registry.register(ToolSpec("create", lambda params: calls.append("create") or {"created": True}, rollback="remove"))
    registry.register(ToolSpec("remove", lambda params: calls.append("remove") or {"removed": True}))
    registry.register(ToolSpec("fail", lambda params: (_ for _ in ()).throw(RuntimeError("boom"))))
    loop = PlannerExecutorCritic(registry)
    plan = Plan("criar e falhar", (PlanStep("s1", "criar", "create"), PlanStep("s2", "falhar", "fail")))
    result = loop.execute(plan)
    assert calls == ["create", "remove"]
    assert result["rollback"][0]["status"] == "ok"
    assert not result["critic"]["accepted"]


def test_unknown_tool_is_rejected():
    loop = PlannerExecutorCritic(ToolRegistry())
    plan = Plan("objetivo", (PlanStep("s1", "x", "shell_exec"),))
    with pytest.raises(PermissionError):
        loop.execute(plan)
