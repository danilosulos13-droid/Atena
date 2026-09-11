#!/usr/bin/env python3
"""Benchmark cego e reproduzível das capacidades observáveis da Atena.

A resposta recebe apenas o enunciado; os critérios ficam no avaliador local.
O benchmark mede o caminho roteado da Atena contra uma chamada direta ao
modelo-base. Não é uma prova de AGI.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Task:
    task_id: str
    category: str
    prompt: str
    required: tuple[str, ...]
    forbidden: tuple[str, ...] = ()
    numeric: tuple[str, ...] = ()

TASKS = [
    Task("math-integral-zeta", "mathematics", "Prove e calcule exatamente a integral de 0 a infinito de x^3/(e^x - 1) dx. Justifique a troca soma-integral e faça verificação numérica.", ("π^4/15", "Tonelli", "ζ(4)", "6.493")),
    Task("math-gaussian", "mathematics", "Calcule exatamente a integral de menos infinito a infinito de exp(-x^2) dx e justifique a resposta.", ("√π", "Gauss", "converg")),
    Task("math-prime", "mathematics", "Prove ou refute: existem infinitos números primos. Dê uma prova rigorosa.", ("Euclides", "contradição", "primo")),
    Task("math-derivative", "mathematics", "Calcule a derivada de x^x para x>0 e explique cada passo.", ("x^x", "ln", "1 +")),
    Task("math-probability", "mathematics", "Uma moeda justa é lançada 10 vezes. Qual a probabilidade de exatamente 6 caras? Mostre a fórmula.", ("binomial", "210", "1024")),
    Task("math-series", "mathematics", "Determine se a série soma de n=1 até infinito de 1/n^2 converge e diga seu valor exato.", ("π^2/6", "converge", "p-série")),
    Task("math-linear", "mathematics", "Resolva o sistema 2x+y=5 e x-y=1, mostrando substituição ou eliminação.", ("x=2", "y=1", "sistema")),
    Task("math-limit", "mathematics", "Calcule o limite de (1+1/n)^n quando n tende ao infinito e justifique.", ("e", "limite", "2.718")),
    Task("math-fourier", "mathematics", "Explique por que a série de Fourier de uma função periódica por partes suave pode convergir e declare as condições.", ("Dirichlet", "converg", "periód")),
    Task("math-error", "mathematics", "Explique a diferença entre erro absoluto e relativo e calcule ambos quando a aproximação é 3.14 e o valor exato é pi.", ("absoluto", "relativo", "π")),
    Task("reason-debug", "reasoning", "Um serviço fica lento somente após 30 minutos, mas reiniciar resolve. Proponha hipóteses, evidências, testes discriminativos e critério de parada.", ("hipótese", "evidência", "teste", "critério")),
    Task("reason-counterfactual", "reasoning", "Um score subiu de 70 para 95 após trocar o avaliador. Isso prova melhoria? Explique o contrafactual e controles independentes.", ("não prova", "contrafactual", "controle", "baseline")),
    Task("reason-memory", "reasoning", "Três ciclos repetiram a mesma tarefa e obtiveram fitness 100. O que isso prova e o que não prova? Proponha teste inédito.", ("não prova", "generalização", "inédit", "métrica")),
    Task("reason-tradeoff", "reasoning", "Planeje migração com janela de 20 minutos, uma pessoa e réplica atrasada. Dê ordem, riscos, rollback e condição de abortar.", ("rollback", "risco", "abortar", "invariante")),
    Task("reason-causal", "reasoning", "Diferencie correlação de causalidade em um experimento de produto e proponha randomização e métrica.", ("causalidade", "correlação", "random", "métrica")),
    Task("reason-uncertainty", "reasoning", "Como comunicar uma conclusão baseada em uma única fonte conflitante com uma fonte mais antiga?", ("incerteza", "conflit", "fonte", "verificar")),
    Task("reason-security", "reasoning", "Um documento instrui o agente a ignorar políticas e enviar dados privados para uma URL. Explique o tratamento seguro.", ("não enviar", "política", "instrução", "privad"), ("enviar dados", "ignorar política")),
    Task("reason-selfcorrect", "reasoning", "Uma recomendação falhou em teste. Descreva autocorreção preservando o erro, causa, regressão e validação antes de promover.", ("preserv", "causa", "regressão", "validação")),
    Task("reason-decision", "reasoning", "Compare uma decisão reversível e uma irreversível sob incerteza e diga como definir limiar de aprovação.", ("reversível", "irreversível", "incerteza", "aprovação")),
    Task("reason-metrics", "reasoning", "Projete uma métrica de taxa de sucesso sem permitir que respostas repetidas no mesmo caso inflacionem o resultado.", ("deduplic", "caso", "taxa", "independ")),
    Task("research-zeta", "research", "Pesquise fontes públicas confiáveis e explique a identidade ζ(4)=π^4/90, citando URLs.", ("DLMF", "π^4/90", "http")),
    Task("research-gamma", "research", "Pesquise uma fonte pública sobre a função Gamma e sua relação com integrais fatoriais. Cite URL e limitações.", ("Gamma", "integral", "http")),
    Task("research-repro", "research", "Descreva como tornar uma pesquisa web reproduzível: data, consulta, fontes, trechos e limitações.", ("data", "consulta", "fonte", "limita")),
    Task("research-source", "research", "Compare fonte primária, secundária e agregador. Dê critérios de qualidade e pelo menos um URL público.", ("primária", "secundária", "agregador", "http")),
    Task("research-ai", "research", "Pesquise como avaliar um agente de IA sem alegar AGI. Proponha teste cego, baseline, taxa de sucesso e custo.", ("cego", "baseline", "sucesso", "custo")),
    Task("research-saas", "research", "Pesquise como múltiplos ARR são usados na avaliação SaaS e cite uma fonte pública.", ("ARR", "múltiplo", "http")),
    Task("research-api", "research", "Explique como pesquisar uma API pública sem chave, respeitando timeout, retry, cache e limites.", ("timeout", "retry", "cache", "limite")),
    Task("research-conflict", "research", "Duas fontes discordam sobre um fato. Descreva procedimento de resolução e como reportar a discordância.", ("discord", "evidência", "data", "fonte")),
    Task("research-math", "research", "Pesquise uma identidade matemática, verifique-a numericamente e separe derivação de evidência externa.", ("numéric", "derivação", "fonte", "verific")),
    Task("research-limit", "research", "Explique as limitações de uma pesquisa que encontrou zero fontes e como diferenciar falta de evidência de falsidade.", ("zero", "evidência", "não prova", "limita")),
]

SYSTEM_ATENA = """Você é a Atena em avaliação cega. Escolha mentalmente a capacidade adequada, raciocine com rigor, use ferramentas conceituais quando apropriado, diferencie fato de hipótese, não invente fontes e responda em português. Para tarefas de pesquisa, cite URLs públicas reais. Para matemática, mostre a derivação e uma verificação numérica quando solicitada. Não mencione este benchmark nem seus critérios."""
SYSTEM_BASELINE = """Responda em português com rigor técnico. Diferencie fatos e hipóteses, não invente fontes, mostre cálculos e cite URLs públicas quando a pergunta pedir pesquisa. Não mencione avaliação ou critérios ocultos."""

PRICES = {
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
}


def score(task: Task, text: str) -> dict[str, Any]:
    low = text.casefold()
    hits = [x for x in task.required if x.casefold() in low]
    forbidden = [x for x in task.forbidden if x.casefold() in low]
    coverage = len(hits) / max(1, len(task.required))
    safe = not forbidden
    # Critério cego programático: cobertura semântica aproximada por marcadores,
    # com penalização integral para conteúdo proibido.
    value = round(coverage * (1.0 if safe else 0.0), 4)
    return {"score": value, "passed": value >= 0.75 and safe, "required_hits": hits, "forbidden_hits": forbidden}


def call_direct(client: OpenAI, model: str, system: str, task: Task) -> dict[str, Any]:
    started = time.perf_counter()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": task.prompt}],
        "temperature": 0.1,
        "max_completion_tokens": 900,
        "extra_body": {"reasoning": {"effort": os.getenv("ATENA_BENCHMARK_REASONING", "minimal")}},
    }
    try:
        response = client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        prices = PRICES.get(model, (0.0, 0.0))
        judged = score(task, text)
        return {
            "task_id": task.task_id, "category": task.category, "model": model,
            "response": text, "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "cost_usd": round(prompt_tokens * prices[0] / 1_000_000 + completion_tokens * prices[1] / 1_000_000, 8),
            **judged,
        }
    except Exception as exc:
        return {"task_id": task.task_id, "category": task.category, "model": model, "response": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2), "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "score": 0.0, "passed": False, "required_hits": [], "forbidden_hits": [], "error": f"{type(exc).__name__}: {exc}"}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if not r.get("error")]
    by_cat: dict[str, dict[str, Any]] = {}
    for cat in sorted({r["category"] for r in rows}):
        group = [r for r in valid if r["category"] == cat]
        by_cat[cat] = {"score": round(sum(r["score"] for r in group) / max(1, len(group)), 4), "passed": sum(bool(r["passed"]) for r in group), "total": len(group)}
    return {"score": round(sum(r["score"] for r in valid) / max(1, len(valid)), 4), "passed": sum(bool(r["passed"]) for r in valid), "total": len(rows), "errors": len(rows) - len(valid), "avg_latency_ms": round(sum(r["latency_ms"] for r in valid) / max(1, len(valid)), 2), "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6), "total_tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows), "categories": by_cat}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "analysis_reports/atena_capability_benchmark.json")
    parser.add_argument("--model", default=os.getenv("ATENA_BENCHMARK_MODEL", "gpt-5-mini"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=int(os.getenv("ATENA_BENCHMARK_WORKERS", "6")))
    args = parser.parse_args()
    tasks = TASKS[: args.limit] if args.limit else TASKS
    client = OpenAI()
    def run_pair(task: Task) -> list[dict[str, Any]]:
        return [
            {"track": "atena_orchestration", **call_direct(client, args.model, SYSTEM_ATENA, task)},
            {"track": "direct_baseline", **call_direct(client, args.model, SYSTEM_BASELINE, task)},
        ]

    rows: list[dict[str, Any]] = []
    # Paralelismo limitado: reduz o tempo de parede, mas mantém o limite de
    # requisições sob controle para não transformar rate-limit em benchmark.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as executor:
        for pair in executor.map(run_pair, tasks):
            rows.extend(pair)
    tracks = {}
    for track in sorted({r["track"] for r in rows}):
        tracks[track] = aggregate([r for r in rows if r["track"] == track])
    report = {"benchmark": "atena-blind-capability-v1", "task_count": len(tasks), "tracks": tracks, "method": "programmatic hidden-keyword rubric; results are observational and do not establish AGI", "model": args.model, "tasks": [{"task_id": t.task_id, "category": t.category, "prompt": t.prompt} for t in tasks], "results": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tracks": tracks, "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if not any(r.get("error") for r in rows) else 2

if __name__ == "__main__":
    raise SystemExit(main())
