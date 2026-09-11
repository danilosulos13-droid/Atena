from pathlib import Path

from core.tool_broker import ToolBroker
from core.tool_contracts import Decision, ToolCall


def call(name: str, arguments: dict, risk: str = "read_only") -> ToolCall:
    return ToolCall(
        tool_call_id="tc-test",
        name=name,
        arguments=arguments,
        purpose="teste controlado",
        requested_risk=risk,
    )


def test_memory_search_is_allowlisted_and_side_effect_free(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    result = broker.dispatch(call("memory.search", {"query": "memória antiga", "limit": 2}))
    assert result.status == "executed"
    assert result.side_effect is False
    assert result.result["fixture"] == "memory-v1"
    assert (tmp_path / "audit.jsonl").exists()


def test_sensitive_tasker_action_requires_confirmation_and_never_executes(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    result = broker.dispatch(call("tasker.send_message", {"action": "send_message", "target": "user", "parameters": {}}))
    assert result.status == "blocked"
    assert result.approval_required is True
    assert result.side_effect is False


def test_unknown_tool_and_invalid_arguments_are_rejected(tmp_path: Path):
    broker = ToolBroker(tmp_path / "audit.jsonl")
    unknown = broker.dispatch(call("shell.exec", {"command": "echo unsafe"}))
    invalid = broker.dispatch(call("memory.search", {"query": "x", "limit": 999}))
    assert unknown.status == "invalid"
    assert invalid.status == "invalid"


def test_decision_requires_payload_for_kind():
    try:
        Decision(kind="tool_call")
    except ValueError as exc:
        assert "tool_call" in str(exc)
    else:
        raise AssertionError("Decision inválida foi aceita")
