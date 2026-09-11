"""Broker de ferramentas e adaptadores seguros para a Atena.

O broker continua responsável por allowlist, validação, aprovação e auditoria.
``BrokerToolAdapter`` permite registrar uma ferramenta do broker no
``PlannerExecutorCritic`` sem expor diretamente seus executores internos.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.tool_contracts import Risk, ToolCall, ToolResult


class MemorySearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)


class WebSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)
    domain: str | None = Field(default=None, max_length=120)


class RunTestsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_./-]+$")
    timeout_seconds: int = Field(default=10, ge=1, le=30)


class TaskerArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=80)
    target: str = Field(default="sandbox-device", min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)


class GithubArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1, max_length=200)
    operation: str = Field(min_length=1, max_length=80)


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    risk: str
    confirmation: bool
    sandbox_mode: str
    executor_name: str


Executor = Callable[[dict[str, Any]], dict[str, Any]]


class BrokerToolError(RuntimeError):
    """Erro de despacho preservando o resultado auditável do broker."""

    def __init__(self, result: ToolResult):
        self.result = result
        super().__init__(result.error_code or f"tool {result.name} não executada")


class BrokerToolAdapter:
    """Adapta uma ferramenta do ``ToolBroker`` para um ``ToolSpec``.

    O adaptador cria um ``ToolCall`` novo a cada execução, delega toda a
    validação/política ao broker e devolve um envelope com evidência para o
    Critic. Resultados bloqueados, inválidos ou com erro viram exceção para que
    o Planner registre a etapa como falha, sem mascarar o motivo original.
    """

    def __init__(
        self,
        broker: "ToolBroker",
        tool_name: str,
        *,
        purpose: str,
        requested_risk: Risk = "read_only",
        requires_approval: bool = False,
    ) -> None:
        if tool_name not in broker.policies:
            raise ValueError(f"ferramenta não allowlisted: {tool_name}")
        self.broker = broker
        self.tool_name = tool_name
        self.purpose = purpose
        self.requested_risk = requested_risk
        self.requires_approval = requires_approval

    def __call__(self, parameters: dict[str, Any]) -> dict[str, Any]:
        call = ToolCall(
            tool_call_id=f"broker-{uuid.uuid4().hex}",
            name=self.tool_name,
            arguments=dict(parameters),
            purpose=self.purpose,
            requested_risk=self.requested_risk,
            requires_confirmation=self.requires_approval,
        )
        result = self.broker.dispatch(call, approval=False)
        if result.status != "executed":
            raise BrokerToolError(result)
        evidence = [f"tool://{result.name}/{result.tool_call_id}"]
        payload = dict(result.result)
        existing = payload.get("evidence")
        payload["evidence"] = evidence + ([str(item) for item in existing] if isinstance(existing, list) else [])
        payload["tool_result"] = result.model_dump(mode="json")
        return payload


class ToolBroker:
    def __init__(self, audit_path: Path | None = None) -> None:
        self.audit_path = audit_path
        self.policies: dict[str, ToolPolicy] = {
            "memory.search": ToolPolicy(name="memory.search", risk="read_only", confirmation=False, sandbox_mode="mock", executor_name="memory_search"),
            "web.search": ToolPolicy(name="web.search", risk="read_only", confirmation=False, sandbox_mode="mock", executor_name="web_search"),
            "code.run_tests": ToolPolicy(name="code.run_tests", risk="sandbox_compute", confirmation=False, sandbox_mode="temporary_fs", executor_name="run_tests"),
            "tasker.open_app": ToolPolicy(name="tasker.open_app", risk="device_side_effect", confirmation=False, sandbox_mode="mock", executor_name="tasker_mock"),
            "tasker.send_message": ToolPolicy(name="tasker.send_message", risk="sensitive_side_effect", confirmation=True, sandbox_mode="disabled", executor_name="tasker_mock"),
            "tasker.call": ToolPolicy(name="tasker.call", risk="sensitive_side_effect", confirmation=True, sandbox_mode="disabled", executor_name="tasker_mock"),
            "github.push": ToolPolicy(name="github.push", risk="external_write", confirmation=True, sandbox_mode="disabled", executor_name="github_mock"),
        }
        self.argument_models: dict[str, type[BaseModel]] = {
            "memory.search": MemorySearchArgs,
            "web.search": WebSearchArgs,
            "code.run_tests": RunTestsArgs,
            "tasker.open_app": TaskerArgs,
            "tasker.send_message": TaskerArgs,
            "tasker.call": TaskerArgs,
            "github.push": GithubArgs,
        }
        self.executors: dict[str, Executor] = {
            "memory_search": self._memory_search,
            "web_search": self._web_search,
            "run_tests": self._run_tests,
            "tasker_mock": self._tasker_mock,
            "github_mock": self._github_mock,
        }

    def register_executor(self, executor_name: str, executor: Executor) -> None:
        """Registra um executor injetável para composição em produção/testes."""
        if not executor_name or not callable(executor):
            raise ValueError("executor inválido")
        self.executors[executor_name] = executor

    def bind_tool(self, tool_name: str, executor_name: str, *, sandbox_mode: str | None = None) -> None:
        """Liga uma policy allowlisted a um executor registrado."""
        policy = self.policies.get(tool_name)
        if policy is None:
            raise ValueError(f"ferramenta não allowlisted: {tool_name}")
        if executor_name not in self.executors:
            raise ValueError(f"executor não registrado: {executor_name}")
        self.policies[tool_name] = policy.model_copy(update={
            "executor_name": executor_name,
            **({"sandbox_mode": sandbox_mode} if sandbox_mode is not None else {}),
        })

    def dispatch(self, call: ToolCall, *, approval: bool = False) -> ToolResult:
        started = time.perf_counter()
        policy = self.policies.get(call.name)
        if policy is None:
            return self._result(call, "invalid", "tool_not_allowlisted", started)

        model = self.argument_models[call.name]
        try:
            arguments = model.model_validate(call.arguments).model_dump(mode="json")
        except ValidationError:
            return self._result(call, "invalid", "invalid_arguments", started)

        if policy.confirmation and not approval:
            return self._result(call, "blocked", "explicit_confirmation_required", started, approval_required=True)
        if policy.sandbox_mode == "disabled":
            return self._result(call, "blocked", "real_side_effects_disabled_in_benchmark", started, approval_required=policy.confirmation, approval_received=approval)

        try:
            result = self.executors[policy.executor_name](arguments)
            envelope = ToolResult(
                tool_call_id=call.tool_call_id,
                name=call.name,
                status="executed",
                result=result,
                side_effect=False,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                sandbox_mode=policy.sandbox_mode,
            )
        except Exception as exc:
            envelope = ToolResult(
                tool_call_id=call.tool_call_id,
                name=call.name,
                status="tool_error",
                error_code=type(exc).__name__,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                sandbox_mode=policy.sandbox_mode,
            )
        self._audit(call, envelope)
        return envelope

    def _result(self, call: ToolCall, status: str, error: str, started: float, *, approval_required: bool = False, approval_received: bool = False) -> ToolResult:
        envelope = ToolResult(
            tool_call_id=call.tool_call_id,
            name=call.name,
            status=status,  # type: ignore[arg-type]
            error_code=error,
            approval_required=approval_required,
            approval_received=approval_received,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            sandbox_mode="disabled" if error.startswith("real_") else "mock",
        )
        self._audit(call, envelope)
        return envelope

    def _audit(self, call: ToolCall, result: ToolResult) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": time.time(),
            "call": call.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()

    @staticmethod
    def _memory_search(arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments["query"].casefold()
        records = [
            {"id": "fixture-memory-1", "text": "A mudança foi proposta, mas não há teste independente.", "confidence": 0.2},
            {"id": "fixture-memory-2", "text": "O rollback foi testado em sandbox sem efeitos externos.", "confidence": 0.8},
        ]
        matches = [item for item in records if any(word in item["text"].casefold() for word in query.split() if len(word) > 3)]
        return {"items": matches[: arguments["limit"]], "fixture": "memory-v1"}

    @staticmethod
    def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(arguments["query"].encode()).hexdigest()[:12]
        return {"items": [{"title": "Fixture de pesquisa controlada", "url": f"sandbox://web/{digest}", "verified": False}], "network": False, "fixture": "web-v1"}

    @staticmethod
    def _run_tests(arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments["target"]
        return {
            "target": target,
            "passed": True,
            "executed_in": "temporary_fs",
            "network": False,
            "evidence": [f"test://temporary-fs/{target}"],
        }

    @staticmethod
    def _tasker_mock(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"simulated": True, "action": arguments["action"], "device_state_changed": False}

    @staticmethod
    def _github_mock(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"simulated": True, "repository": arguments["repository"], "operation": arguments["operation"], "remote_changed": False}
