from pathlib import Path

import pytest

from core.agent_plan_loop import Plan, PlanStep, PlannerExecutorCritic, ToolRegistry, ToolSpec
from core.tool_broker import BrokerToolAdapter, BrokerToolError, ToolBroker
from core.tool_contracts import ToolCall


def test_adapter_executes_allowlisted_tool_and_emits_evidence(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    adapter = BrokerToolAdapter(
        broker,
        "memory.search",
        purpose="validar contexto do ciclo",
    )
    registry = ToolRegistry()
    registry.register(ToolSpec("memory_search", adapter))
    result = PlannerExecutorCritic(registry).execute(
        Plan(
            "buscar memória",
            (PlanStep("s1", "buscar", "memory_search", {"query": "rollback", "limit": 2}, success_criteria=("evidence",)),),
        )
    )
    assert result["critic"]["accepted"] is True
    assert result["observations"][0]["output"]["tool_result"]["status"] == "executed"
    assert result["observations"][0]["evidence"]
    assert (tmp_path / "audit.jsonl").exists()


def test_adapter_propagates_blocked_tool_without_side_effect(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    adapter = BrokerToolAdapter(
        broker,
        "github.push",
        purpose="proposta de teste",
        requested_risk="external_write",
        requires_approval=True,
    )
    with pytest.raises(BrokerToolError) as caught:
        adapter({"repository": "org/repo", "operation": "push"})
    assert caught.value.result.status == "blocked"
    assert caught.value.result.error_code == "explicit_confirmation_required"
    assert caught.value.result.side_effect is False


def test_adapter_rejects_unknown_tool(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError, match="não allowlisted"):
        BrokerToolAdapter(broker, "shell.exec", purpose="unsafe")


def test_broker_rejects_invalid_adapter_arguments(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    adapter = BrokerToolAdapter(broker, "memory.search", purpose="teste")
    with pytest.raises(BrokerToolError) as caught:
        adapter({"query": "x", "limit": 999})
    assert caught.value.result.status == "invalid"
