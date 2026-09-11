"""Seleção auditável de capacidades para o ciclo autônomo da Atena.

A camada decide primeiro qual capacidade é apropriada; só depois o ciclo
executa pesquisa e registra evidências. Capacidades desconhecidas retornam ao
fluxo RSS genérico, sem fingir que uma ferramenta especializada foi usada.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityDecision:
    name: str
    tools: tuple[str, ...]
    reason: str
    confidence: float


_CAPABILITY_RULES = (
    (
        "mathematics",
        ("integral", "derivada", "limite", "equação", "teorema", "prova", "zeta", "matemática", "matematica", "sympy"),
        ("deep_web_research", "direct_public_math_sources", "mpmath", "symbolic_derivation"),
        "A pergunta contém sinais de cálculo, prova ou matemática; usar fontes matemáticas públicas e verificação numérica local.",
    ),
    (
        "software_engineering",
        ("código", "codigo", "python", "api", "bug", "teste", "programação", "programacao", "software"),
        ("deep_web_research", "repository_inspection", "pytest"),
        "A pergunta parece exigir inspeção técnica, documentação e teste reproduzível.",
    ),
    (
        "general_research",
        (),
        ("rss_and_public_web_research", "evidence_memory"),
        "Nenhuma capacidade especializada foi identificada; usar a pesquisa pública geral e memória de evidências.",
    ),
)


def select_capability(topic: str, question: str) -> CapabilityDecision:
    text = f"{topic} {question}".casefold()
    for name, markers, tools, reason in _CAPABILITY_RULES:
        if markers and any(marker in text for marker in markers):
            return CapabilityDecision(name, tools, reason, 0.9)
    name, _, tools, reason = _CAPABILITY_RULES[-1]
    return CapabilityDecision(name, tools, reason, 0.55)


def _math_result_to_research(result: dict[str, Any], decision: CapabilityDecision, topic: str, question: str, mode: str) -> dict[str, Any]:
    sources = []
    for source in result.get("sources", []):
        if not isinstance(source, dict):
            continue
        sources.append({
            "source": source.get("title", "fonte matemática pública"),
            "category": "mathematics",
            "ok": True,
            "details": source.get("snippet", ""),
            "source_url": source.get("url"),
            "url": source.get("url"),
        })
    return {
        "topic": topic,
        "question": question,
        "query": question,
        "mode": mode,
        "capability": asdict(decision),
        "sources": sources,
        "rss_sources": [],
        "errors": [],
        "specialized_answer": result.get("answer", ""),
        "specialized_metadata": result.get("math_verification"),
        "report_json": result.get("json_path"),
        "report_markdown": result.get("markdown_path"),
    }


def research_for_capability(topic: str, question: str, *, mode: str = "autonomous") -> dict[str, Any] | None:
    """Executa a capacidade especializada quando há uma decisão segura.

    Retorna ``None`` para capacidades ainda não implementadas, permitindo que
    o ciclo preserve o coletor RSS existente para tarefas gerais.
    """
    decision = select_capability(topic, question)
    if decision.name != "mathematics":
        return None

    from core.research_orchestrator import run_deep_research

    result = run_deep_research(
        question,
        topic="matemática",
        limit_per_query=3,
        max_sources=6,
        use_llm=False,
    )
    return _math_result_to_research(result, decision, topic, question, mode)


__all__ = ["CapabilityDecision", "research_for_capability", "select_capability"]
