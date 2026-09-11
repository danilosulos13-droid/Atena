"""Ciclo seguro Planner -> Executor -> Critic para missões da Atena.

O executor só chama ferramentas registradas explicitamente. Ações sensíveis
exigem aprovação fornecida pelo chamador; falhas acionam rollback registrado.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Mapping
import hashlib
import time


@dataclass(frozen=True)
class PlanStep:
    id: str
    objective: str
    tool: str
    parameters: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"
    requires_approval: bool = False
    success_criteria: tuple[str, ...] = ()
    rollback_tool: str | None = None


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()
    obstacles: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepObservation:
    step_id: str
    status: str
    output: Any = None
    evidence: tuple[str, ...] = ()
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[[dict[str, Any]], Any]
    risk: str = "low"
    requires_approval: bool = False
    rollback: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or spec.name.startswith(("shell", "exec", "eval")):
            raise ValueError("nome de ferramenta não permitido")
        if spec.name in self._tools:
            raise ValueError(f"ferramenta já registrada: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise PermissionError(f"ferramenta fora da allowlist: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


class PlannerExecutorCritic:
    def __init__(self, registry: ToolRegistry, *, max_steps: int = 12) -> None:
        self.registry = registry
        self.max_steps = max_steps

    def validate_plan(self, plan: Plan) -> None:
        if not plan.goal.strip():
            raise ValueError("objetivo vazio")
        if not plan.steps or len(plan.steps) > self.max_steps:
            raise ValueError("quantidade de etapas inválida")
        seen: set[str] = set()
        for step in plan.steps:
            if step.id in seen:
                raise ValueError(f"id de etapa duplicado: {step.id}")
            seen.add(step.id)
            tool = self.registry.get(step.tool)
            if step.requires_approval and not tool.requires_approval:
                raise ValueError("a etapa não pode relaxar a política da ferramenta")
            if tool.requires_approval and not step.requires_approval:
                raise ValueError(f"aprovação obrigatória para {step.tool}")
            if step.risk not in {"low", "medium", "high", "critical"}:
                raise ValueError("nível de risco inválido")

    def execute(self, plan: Plan, *, approvals: set[str] | None = None) -> dict[str, Any]:
        self.validate_plan(plan)
        approvals = approvals or set()
        observations: list[StepObservation] = []
        completed: list[PlanStep] = []
        failed_step: PlanStep | None = None
        for step in plan.steps:
            tool = self.registry.get(step.tool)
            if tool.requires_approval and step.id not in approvals:
                observations.append(StepObservation(step.id, "awaiting_approval", error="aprovação explícita ausente"))
                failed_step = step
                break
            started = time.perf_counter()
            try:
                output = tool.handler(dict(step.parameters))
                evidence = self._extract_evidence(output)
                observations.append(StepObservation(step.id, "ok", output, evidence, elapsed_ms=round((time.perf_counter() - started) * 1000, 2)))
                completed.append(step)
            except Exception as exc:
                observations.append(StepObservation(step.id, "failed", error=f"{type(exc).__name__}: {exc}", elapsed_ms=round((time.perf_counter() - started) * 1000, 2)))
                failed_step = step
                break
        rollback: list[dict[str, Any]] = []
        if failed_step is not None:
            for step in reversed(completed):
                rollback_name = step.rollback_tool or self.registry.get(step.tool).rollback
                if not rollback_name:
                    continue
                try:
                    rollback_output = self.registry.get(rollback_name).handler(dict(step.parameters))
                    rollback.append({"step_id": step.id, "status": "ok", "tool": rollback_name, "output": rollback_output})
                except Exception as exc:
                    rollback.append({"step_id": step.id, "status": "failed", "tool": rollback_name, "error": f"{type(exc).__name__}: {exc}"})
        critic = self.critic(plan, observations, rollback)
        return {"plan": asdict(plan), "observations": [asdict(item) for item in observations], "rollback": rollback, "critic": critic}

    def critic(self, plan: Plan, observations: list[StepObservation], rollback: list[dict[str, Any]]) -> dict[str, Any]:
        failed = [item for item in observations if item.status != "ok"]
        missing_evidence = [step.id for step, item in zip(plan.steps, observations) if item.status == "ok" and step.success_criteria and not item.evidence]
        rollback_failures = [item for item in rollback if item.get("status") != "ok"]
        accepted = not failed and not missing_evidence and not rollback_failures
        return {"accepted": accepted, "failed_steps": [item.step_id for item in failed], "missing_evidence": missing_evidence, "rollback_failures": rollback_failures, "explanation": "plano concluído e verificado" if accepted else "revisão necessária antes de declarar sucesso"}

    @staticmethod
    def _extract_evidence(output: Any) -> tuple[str, ...]:
        if isinstance(output, Mapping):
            values = output.get("evidence") or output.get("evidence_refs") or ()
            if isinstance(values, (list, tuple)):
                return tuple(str(item) for item in values if str(item).strip())
        return ()


def plan_fingerprint(plan: Plan) -> str:
    payload = repr(asdict(plan)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
