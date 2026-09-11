"""Roteamento determinístico de tarefas entre provedores LLM.

A seleção é uma preferência, nunca uma autorização para executar ações. A política
pode ser sobrescrita por ATENA_ROUTE_<TASK> e usa fallback quando o provider não
está configurado ou saudável.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    task_type: str
    preferred_provider: str | None
    fallback_providers: tuple[str, ...]
    reason: str


_DEFAULT_ROUTES: dict[str, tuple[str | None, tuple[str, ...], str]] = {
    "simple": ("local", ("gemini", "anthropic"), "tarefas simples priorizam privacidade e latência local"),
    "telegram": ("local", ("gemini", "anthropic"), "conversas comuns priorizam o modelo local"),
    "private": ("local", (), "conteúdo privado não deve sair do servidor por padrão"),
    "research": ("gemini", ("anthropic", "local"), "pesquisa e síntese se beneficiam de grounding e contexto amplo"),
    "web_research": ("gemini", ("anthropic", "local"), "pesquisa web atual prioriza multimodalidade e ferramentas"),
    "code": ("anthropic", ("gemini", "local"), "código e depuração priorizam raciocínio de engenharia"),
    "github_evolution": ("anthropic", ("gemini", "local"), "alterações no GitHub exigem revisão de código e testes"),
    "architecture": ("anthropic", ("gemini", "local"), "arquitetura exige planejamento longo e análise de trade-offs"),
    "multimodal": ("gemini", ("anthropic", "local"), "imagem, áudio e vídeo priorizam entrada multimodal"),
    "voice": ("gemini", ("local", "anthropic"), "voz prioriza latência e capacidades multimodais"),
    "local": ("local", (), "execução estritamente local solicitada"),
    "auto": (None, ("local", "gemini", "anthropic"), "roteador automático usa providers saudáveis"),
}


def _normalize(task_type: str | None) -> str:
    value = (task_type or "auto").strip().casefold().replace("-", "_").replace(" ", "_")
    return value if value in _DEFAULT_ROUTES else "auto"


def _env_override(task_type: str) -> str | None:
    key = "ATENA_ROUTE_" + task_type.upper()
    value = os.getenv(key, "").strip().casefold()
    return value or None


def route_for_task(task_type: str | None = None) -> RouteDecision:
    normalized = _normalize(task_type)
    preferred, fallbacks, reason = _DEFAULT_ROUTES[normalized]
    override = _env_override(normalized)
    if override:
        allowed = {"local", "gemini", "anthropic", "none"}
        if override in allowed:
            preferred = None if override == "none" else override
            reason = f"override explícito via ATENA_ROUTE_{normalized.upper()}"
    return RouteDecision(normalized, preferred, fallbacks, reason)


def provider_order(task_type: str | None, available: list[str]) -> list[str]:
    decision = route_for_task(task_type)
    ordered: list[str] = []
    for provider in ((decision.preferred_provider,) + decision.fallback_providers):
        if provider and provider in available and provider not in ordered:
            ordered.append(provider)
    for provider in available:
        if provider not in ordered:
            ordered.append(provider)
    return ordered
