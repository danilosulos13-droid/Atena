import json
from pathlib import Path

import pytest

from core.agent_plan_loop import PlanStep, ToolRegistry, ToolSpec
from core.unified_agent_cycle import UnifiedAgentCycle, default_cycle


def test_default_cycle_runs_objective_plan_execution_and_critic(tmp_path: Path):
    audit = tmp_path / "cycles.jsonl"
    outcome = default_cycle(audit_path=audit).run("observar fontes e registrar evidência")

    assert outcome.accepted is True
    assert outcome.status == "accepted"
    assert outcome.result["critic"]["accepted"] is True
    assert len(outcome.result["observations"]) == 2
    assert audit.exists()
    saved = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert saved["cycle_id"] == outcome.cycle_id
    assert saved["plan_fingerprint"] == outcome.plan_fingerprint


def test_unknown_tool_is_rejected_before_execution(tmp_path: Path):
    registry = ToolRegistry()
    cycle = UnifiedAgentCycle(registry, audit_path=tmp_path / "cycles.jsonl")
    steps = [PlanStep("s1", "tarefa", "nao-allowlisted")]

    with pytest.raises(PermissionError):
        cycle.run("objetivo", steps=steps)


def test_approval_required_blocks_and_critic_rejects(tmp_path: Path):
    registry = ToolRegistry()
    calls = []
    registry.register(ToolSpec("sensitive", lambda params: calls.append(params), requires_approval=True))
    cycle = UnifiedAgentCycle(registry, audit_path=tmp_path / "cycles.jsonl")
    steps = [PlanStep("s1", "ação sensível", "sensitive", requires_approval=True)]

    outcome = cycle.run("objetivo sensível", steps=steps)

    assert outcome.accepted is False
    assert outcome.status == "needs_review"
    assert outcome.result["observations"][0]["status"] == "awaiting_approval"
    assert calls == []


def test_failure_triggers_registered_rollback(tmp_path: Path):
    registry = ToolRegistry()
    calls = []

    def first(params):
        calls.append("first")
        return {"evidence": ["first_done"]}

    def second(params):
        calls.append("second")
        raise RuntimeError("falha controlada")

    def rollback(params):
        calls.append("rollback")
        return {"evidence": ["rolled_back"]}

    registry.register(ToolSpec("first", first, rollback="rollback"))
    registry.register(ToolSpec("second", second))
    registry.register(ToolSpec("rollback", rollback))
    cycle = UnifiedAgentCycle(registry, audit_path=tmp_path / "cycles.jsonl")
    steps = [
        PlanStep("s1", "primeiro", "first"),
        PlanStep("s2", "segundo", "second"),
    ]

    outcome = cycle.run("objetivo", steps=steps)

    assert outcome.accepted is False
    assert calls == ["first", "second", "rollback"]
    assert outcome.result["rollback"][0]["status"] == "ok"
    assert outcome.result["critic"]["failed_steps"] == ["s2"]
