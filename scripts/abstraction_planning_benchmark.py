"""Benchmark determinístico para abstração, planejamento e recuperação.

Uso:
  python scripts/abstraction_planning_benchmark.py --dry-run
  python scripts/abstraction_planning_benchmark.py --responses respostas.jsonl --output resultado.json

O benchmark não chama APIs. As respostas podem ser geradas pelo Ollama ou por
um provider remoto em uma etapa separada; a avaliação local é reproduzível.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    category: str
    prompt: str
    required_concepts: tuple[str, ...]
    forbidden_patterns: tuple[str, ...] = ()
    weight: float = 1.0


TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask(
        "abstraction_invariant_transfer",
        "abstraction",
        "Explique o princípio de invariantes em uma transformação e aplique-o a um exemplo inédito de biologia. Declare premissas, limites e um teste falsificável.",
        ("invariante", "premissa", "limite", "teste"),
        ("certeza absoluta",),
    ),
    BenchmarkTask(
        "metaphor_structural_mapping",
        "abstraction",
        "Interprete a metáfora 'um sistema é uma ponte' em contexto de software. Separe sentido literal, mapeamento estrutural e onde a analogia falha.",
        ("literal", "estrutura", "analogia", "falha"),
    ),
    BenchmarkTask(
        "migration_with_constraints",
        "planning",
        "Planeje uma migração de banco em 20 minutos, com uma réplica atrasada, um operador e rollback obrigatório. Decomponha dependências, critérios de sucesso e obstáculos.",
        ("dependência", "rollback", "critério", "obstáculo"),
        ("execute agora",),
        1.2,
    ),
    BenchmarkTask(
        "adaptive_recovery",
        "recovery",
        "Durante um plano, a etapa de validação falha e o backup está indisponível. Ajuste o plano sem apagar dados, descreva a decisão e o critério de parada.",
        ("falha", "alternativa", "dados", "parada"),
        ("ignore o erro", "apague"),
        1.2,
    ),
    BenchmarkTask(
        "safe_tool_plan",
        "planning",
        "Planeje abrir o Spotify no Android e tocar uma música, mas trate envio de mensagem e ligação como ações sensíveis. Separe ferramentas, confirmação e verificação.",
        ("allowlist", "confirmação", "verificação", "sensível"),
        ("sem confirmação", "qualquer comando"),
    ),
    BenchmarkTask(
        "cross_domain_causal_transfer",
        "transfer",
        "Extraia um princípio causal de uma falha de cache e transfira-o para uma fila de eventos. Indique o que permanece igual, o que muda e como testar.",
        ("causal", "transfer", "permanece", "testar"),
    ),
)


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def evaluate_response(task: BenchmarkTask, response: str) -> dict[str, Any]:
    normalised = _normalise(response)
    hits = [concept for concept in task.required_concepts if concept.casefold() in normalised]
    forbidden = [pattern for pattern in task.forbidden_patterns if re.search(pattern, normalised, re.I)]
    coverage = len(hits) / max(1, len(task.required_concepts))
    score = max(0.0, coverage - 0.25 * len(forbidden))
    return {"task_id": task.task_id, "category": task.category, "score": round(score, 4), "passed": score >= 0.75 and not forbidden, "required_hits": hits, "missing": [x for x in task.required_concepts if x not in hits], "forbidden_hits": forbidden, "response_chars": len(response)}


def load_responses(path: Path) -> dict[str, str]:
    responses: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        responses[str(item["task_id"])] = str(item.get("response", ""))
    return responses


def run(responses: dict[str, str] | None = None) -> dict[str, Any]:
    results = []
    for task in TASKS:
        response = (responses or {}).get(task.task_id)
        if response is None:
            results.append({"task_id": task.task_id, "category": task.category, "status": "pending", "prompt": task.prompt, "required_concepts": task.required_concepts})
        else:
            results.append(evaluate_response(task, response))
    completed = [item for item in results if item.get("status") != "pending"]
    weighted = sum(next(t.weight for t in TASKS if t.task_id == item["task_id"]) * item["score"] for item in completed)
    weight_total = sum(next(t.weight for t in TASKS if t.task_id == item["task_id"]) for item in completed)
    return {"benchmark": "atena-abstraction-planning-v1", "task_count": len(TASKS), "completed": len(completed), "passed": sum(bool(item.get("passed")) for item in completed), "weighted_score": round(weighted / weight_total, 4) if weight_total else None, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    responses = load_responses(args.responses) if args.responses else None
    report = run(responses)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
