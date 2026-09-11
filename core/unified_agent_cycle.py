"""Ciclo unificado e auditável de objetivo -> plano -> execução -> crítica."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from core.agent_plan_loop import (
        Plan,
        PlanStep,
        PlannerExecutorCritic,
        ToolRegistry,
        ToolSpec,
        plan_fingerprint,
    )
except ModuleNotFoundError:  # execução direta do arquivo
    from agent_plan_loop import (  # type: ignore
        Plan,
        PlanStep,
        PlannerExecutorCritic,
        ToolRegistry,
        ToolSpec,
        plan_fingerprint,
    )


@dataclass(frozen=True)
class CycleResult:
    cycle_id: str
    objective: str
    plan_fingerprint: str
    status: str
    accepted: bool
    result: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decompose_objective(objective: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[.;\n]", objective) if part.strip()]
    if len(parts) <= 1 and " e " in objective:
        parts = [part.strip() for part in objective.split(" e ") if part.strip()]
    return parts or [objective.strip()]


class UnifiedAgentCycle:
    """Orquestra uma missão inteira sem permitir ferramentas fora da allowlist."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        max_steps: int = 12,
        audit_path: str | Path = "atena_evolution/unified_cycles.jsonl",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.max_steps = max_steps
        self.audit_path = Path(audit_path)
        self.clock = clock
        self.executor = PlannerExecutorCritic(self.registry, max_steps=max_steps)

    def register_tool(self, spec: ToolSpec) -> None:
        self.registry.register(spec)

    def build_plan(self, objective: str, steps: list[PlanStep] | None = None) -> Plan:
        if steps is not None:
            return Plan(goal=objective, steps=tuple(steps))
        decomposed = _decompose_objective(objective)
        plan_steps = tuple(
            PlanStep(
                id=f"step-{index + 1}",
                objective=step,
                tool="observe_objective",
                parameters={"objective": step},
                risk="low",
                success_criteria=("observation_recorded",),
            )
            for index, step in enumerate(decomposed[: self.max_steps])
        )
        return Plan(goal=objective, steps=plan_steps)

    def run(
        self,
        objective: str,
        *,
        steps: list[PlanStep] | None = None,
        approvals: set[str] | None = None,
    ) -> CycleResult:
        cycle_id = f"cycle-{uuid.uuid4().hex[:12]}"
        plan = self.build_plan(objective, steps)
        self.executor.validate_plan(plan)
        execution = self.executor.execute(plan, approvals=approvals)
        accepted = bool(execution.get("critic", {}).get("accepted", False))
        status = "accepted" if accepted else "needs_review"
        result = CycleResult(
            cycle_id=cycle_id,
            objective=objective,
            plan_fingerprint=plan_fingerprint(plan),
            status=status,
            accepted=accepted,
            result=execution,
            created_at=self.clock(),
        )
        self._persist(result)
        return result

    def _persist(self, result: CycleResult) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result.to_dict(), ensure_ascii=False, default=str) + "\n")
        except OSError:
            # Falha de auditoria não altera a decisão do ciclo, mas o chamador
            # consegue detectar a ausência do arquivo no healthcheck.
            return


def default_cycle(*, audit_path: str | Path = "atena_evolution/unified_cycles.jsonl") -> UnifiedAgentCycle:
    """Cria um ciclo mínimo seguro, com uma única ferramenta de observação."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="observe_objective",
            handler=lambda params: {
                "observed": str(params.get("objective", "")).strip(),
                "evidence": ["local_objective_observation"],
            },
            risk="low",
        )
    )
    return UnifiedAgentCycle(registry, audit_path=audit_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Executa o ciclo unificado seguro da Atena")
    parser.add_argument("objective")
    parser.add_argument("--audit-path", default="atena_evolution/unified_cycles.jsonl")
    args = parser.parse_args()
    outcome = default_cycle(audit_path=args.audit_path).run(args.objective)
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome.accepted else 2)
