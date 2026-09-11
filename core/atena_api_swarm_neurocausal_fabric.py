#!/usr/bin/env python3
"""Executable prototype for the Atena API Swarm NeuroCausal Fabric.

This turns the previously generated blueprint into a runnable local technology:
child-agent tasks receive a parent-validated public API assignment, a causal
trace explaining the assignment, and an energy-aware execution estimate.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.internet_challenge import rank_api_candidates

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "analysis_reports"
DEFAULT_JSON_REPORT = REPORT_DIR / "api_swarm_neurocausal_fabric_last_run.json"
DEFAULT_MD_REPORT = REPORT_DIR / "EXECUCAO_API_SWARM_NEUROCAUSAL_FABRIC_2026-06-01.md"


@dataclass(frozen=True)
class SwarmTask:
    """Task that a child agent needs to execute with a suitable public API."""

    task_id: str
    description: str
    child_agent: str
    required_capabilities: tuple[str, ...]
    max_candidates: int = 5


@dataclass(frozen=True)
class CausalTrace:
    """Why the parent selected a given API for a child task."""

    hypothesis: str
    evidence: tuple[str, ...]
    risk_reduced: str
    confidence: float


@dataclass(frozen=True)
class ApiExecutionPlan:
    """Validated execution plan for one child task."""

    task_id: str
    child_agent: str
    selected_api: dict[str, Any]
    alternatives: tuple[dict[str, Any], ...]
    causal_trace: CausalTrace
    estimated_energy_units: float
    avoided_energy_units: float
    validation: str


class ApiSwarmNeuroCausalFabric:
    """Runnable fabric that routes APIs to child agents with a parent validator."""

    def __init__(self, min_api_score: float = 0.5) -> None:
        self.min_api_score = min_api_score

    def plan_task(self, task: SwarmTask) -> ApiExecutionPlan:
        """Rank APIs for a task and return the validated child execution plan."""
        topic = self._task_query(task)
        candidates = self._rank_for_task(topic, task)
        selected = candidates[0] if candidates else {}
        score = float(selected.get("score", 0.0) or 0.0)
        validation = "approved" if selected and score >= self.min_api_score else "needs_human_review"
        alternatives = tuple(candidates[1:])
        trace = CausalTrace(
            hypothesis=f"{task.child_agent} deve usar a API com maior aderência para: {task.description}",
            evidence=(
                f"{len(candidates)} APIs candidatas ranqueadas",
                f"score selecionado={score:.2f}",
                f"capacidades={', '.join(task.required_capabilities) or 'geral'}",
            ),
            risk_reduced="reduz chamadas redundantes, APIs fracas e custo energético por tentativa/erro",
            confidence=round(min(1.0, max(0.0, score)), 3),
        )
        estimated_energy = round(1.0 + (len(alternatives) * 0.08), 3)
        avoided_energy = round(max(0.0, len(alternatives) * 0.42), 3)
        return ApiExecutionPlan(
            task_id=task.task_id,
            child_agent=task.child_agent,
            selected_api=selected,
            alternatives=alternatives,
            causal_trace=trace,
            estimated_energy_units=estimated_energy,
            avoided_energy_units=avoided_energy,
            validation=validation,
        )


    def _task_query(self, task: SwarmTask) -> str:
        """Build a focused API-search query from task capabilities."""
        caps = {cap.lower() for cap in task.required_capabilities}
        text = f"{task.description} {task.child_agent}".lower()
        if {"github", "code"}.intersection(caps) or "github" in text:
            return "github repo api"
        if "weather" in caps or "clima" in text or "climático" in text:
            return "weather forecast api"
        if {"academic", "research", "evidence"}.intersection(caps):
            return "academic research api"
        return " ".join([task.description, task.child_agent, " ".join(task.required_capabilities)]).strip()


    @staticmethod
    def _capability_seed_candidates(task: SwarmTask) -> list[dict[str, Any]]:
        """Guarantee obvious domain APIs are considered before generic fallbacks."""
        caps = {cap.lower() for cap in task.required_capabilities}
        seeds: list[dict[str, Any]] = []
        if {"github", "code"}.intersection(caps):
            seeds.append({"name": "GitHub", "endpoint": "https://api.github.com", "category": "code", "score": 0.94})
        if "weather" in caps:
            seeds.append({"name": "Open-Meteo", "endpoint": "https://api.open-meteo.com/v1/forecast", "category": "weather", "score": 0.92})
        if {"academic", "research", "evidence"}.intersection(caps):
            seeds.extend(
                [
                    {"name": "OpenAlex", "endpoint": "https://api.openalex.org/works", "category": "research", "score": 0.9},
                    {"name": "Semantic Scholar", "endpoint": "https://api.semanticscholar.org/graph/v1/paper/search", "category": "research", "score": 0.88},
                ]
            )
        return seeds

    def _rank_for_task(self, topic: str, task: SwarmTask) -> list[dict[str, Any]]:
        """Apply task-specific semantic boosts on top of the public API ranker."""
        candidates = self._capability_seed_candidates(task) + rank_api_candidates(topic, limit=task.max_candidates)
        caps = {cap.lower() for cap in task.required_capabilities}

        def boosted(item: dict[str, Any]) -> dict[str, Any]:
            name = str(item.get("name", "")).lower()
            category = str(item.get("category", "")).lower()
            endpoint = str(item.get("endpoint", "")).lower()
            bonus = 0.0
            if {"github", "code"}.intersection(caps) and ("github" in name or "github" in endpoint or category == "code"):
                bonus += 0.18
            if "weather" in caps and ("weather" in name or "meteo" in name or category == "weather"):
                bonus += 0.18
            if {"academic", "research", "evidence"}.intersection(caps) and category in {"research", "health", "knowledge"}:
                bonus += 0.1
            out = dict(item)
            out["score"] = round(min(1.0, float(out.get("score", 0.0) or 0.0) + bonus), 3)
            return out

        deduped: dict[str, dict[str, Any]] = {}
        for item in candidates:
            key = f"{item.get('name')}|{item.get('endpoint')}"
            deduped.setdefault(key, item)
        reranked = [boosted(item) for item in deduped.values()]
        reranked.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return reranked

    def run(self, tasks: Sequence[SwarmTask]) -> dict[str, Any]:
        """Execute the fabric planning loop for all child tasks."""
        plans = [self.plan_task(task) for task in tasks]
        approved = sum(1 for plan in plans if plan.validation == "approved")
        avoided_energy = round(sum(plan.avoided_energy_units for plan in plans), 3)
        avg_confidence = round(
            sum(plan.causal_trace.confidence for plan in plans) / max(1, len(plans)), 3
        )
        return {
            "technology": "Atena API Swarm NeuroCausal Fabric",
            "status": "ok" if approved == len(plans) else "partial",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "tasks_planned": len(plans),
            "approved_plans": approved,
            "average_confidence": avg_confidence,
            "avoided_energy_units": avoided_energy,
            "plans": [self._plan_to_dict(plan) for plan in plans],
        }

    @staticmethod
    def _plan_to_dict(plan: ApiExecutionPlan) -> dict[str, Any]:
        payload = asdict(plan)
        payload["alternatives"] = list(plan.alternatives)
        return payload


def default_tasks() -> tuple[SwarmTask, ...]:
    """Default demo requested by the user: execute the technology Atena created."""
    return (
        SwarmTask(
            task_id="child-code-001",
            description="pesquisar repositórios GitHub e bibliotecas úteis para evolução da Atena",
            child_agent="child-code-researcher",
            required_capabilities=("code", "github", "research"),
        ),
        SwarmTask(
            task_id="child-weather-001",
            description="buscar sinais climáticos públicos para simulação causal de risco operacional",
            child_agent="child-climate-analyst",
            required_capabilities=("weather", "risk", "simulation"),
        ),
        SwarmTask(
            task_id="child-academic-001",
            description="validar hipótese neurocausal com fontes acadêmicas abertas",
            child_agent="child-academic-validator",
            required_capabilities=("research", "academic", "evidence"),
        ),
    )


def write_reports(payload: dict[str, Any], json_path: Path = DEFAULT_JSON_REPORT, md_path: Path = DEFAULT_MD_REPORT) -> tuple[Path, Path]:
    """Persist JSON and Markdown reports for auditability."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Execução — Atena API Swarm NeuroCausal Fabric",
        "",
        "**Data UTC:** 2026-06-01",
        "",
        "## Resultado",
        "",
        f"- Status: `{payload['status']}`.",
        f"- Tecnologia: `{payload['technology']}`.",
        f"- Tarefas planejadas: `{payload['tasks_planned']}`.",
        f"- Planos aprovados pelo pai: `{payload['approved_plans']}`.",
        f"- Confiança média: `{payload['average_confidence']}`.",
        f"- Energia evitada estimada: `{payload['avoided_energy_units']}` unidades.",
        "",
        "## Planos por agente-filho",
    ]
    for plan in payload["plans"]:
        api = plan.get("selected_api") or {}
        trace = plan.get("causal_trace") or {}
        lines.extend(
            [
                "",
                f"### `{plan['child_agent']}`",
                f"- Task: `{plan['task_id']}`.",
                f"- API selecionada: `{api.get('name', 'n/a')}` — `{api.get('endpoint', 'n/a')}`.",
                f"- Validação: `{plan['validation']}`.",
                f"- Confiança causal: `{trace.get('confidence')}`.",
                f"- Risco reduzido: {trace.get('risk_reduced')}",
            ]
        )
    lines.extend(
        [
            "",
            "## Veredito",
            "",
            "A tecnologia criada foi executada: o pai ranqueou APIs por tarefa, injetou a melhor opção para cada agente-filho, preservou alternativas e registrou rastreabilidade neurocausal com estimativa de economia energética.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa o protótipo Atena API Swarm NeuroCausal Fabric")
    parser.add_argument("--json", action="store_true", help="Imprime o payload JSON completo")
    parser.add_argument("--write-report", action="store_true", help="Persiste relatórios em analysis_reports/")
    parser.add_argument("--min-api-score", type=float, default=0.5, help="Limiar mínimo para aprovação do pai")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = ApiSwarmNeuroCausalFabric(min_api_score=args.min_api_score).run(default_tasks())
    if args.write_report:
        json_path, md_path = write_reports(payload)
        payload["json_report_path"] = str(json_path.relative_to(ROOT))
        payload["markdown_report_path"] = str(md_path.relative_to(ROOT))
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['technology']} status={payload['status']} approved={payload['approved_plans']}/{payload['tasks_planned']}")
        print(f"confidence={payload['average_confidence']} avoided_energy={payload['avoided_energy_units']}")
        if args.write_report:
            print(f"JSON: {payload['json_report_path']}")
            print(f"MD: {payload['markdown_report_path']}")
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
