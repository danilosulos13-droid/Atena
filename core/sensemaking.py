"""Sensemaking estruturado para separar fatos, inferências e ações seguras."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse
import re


@dataclass(frozen=True)
class Fact:
    text: str
    source: str = "user"
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True)
class Inference:
    text: str
    basis: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: float = 0.0
    uncertainty: str = ""


@dataclass(frozen=True)
class ActionRecommendation:
    action: str
    rationale: str
    risk: str = "low"
    reversible: bool = True
    requires_confirmation: bool = False


@dataclass(frozen=True)
class SensemakingResult:
    situation: str
    facts: tuple[Fact, ...]
    inferences: tuple[Inference, ...]
    risks: tuple[str, ...]
    recommendations: tuple[ActionRecommendation, ...]
    contradictions: tuple[str, ...] = ()
    needs_clarification: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


COMMON_SENSE_SYSTEM_PROMPT = """Você é o módulo de sensemaking da Atena.
Separe rigorosamente observações, fatos, inferências e recomendações.
Nunca transforme uma inferência em fato. Para cada inferência, informe bases,
premissas, incerteza e confiança entre 0 e 1. Detecte contradições. Se faltarem
dados, peça esclarecimento. Recomendações de alto risco devem ser reversíveis ou
marcadas como exigindo confirmação explícita. Retorne apenas JSON no schema:
{"situation":"...","facts":[],"inferences":[],"risks":[],"recommendations":[],"contradictions":[],"needs_clarification":[]}
"""


def build_prompt(context: str, situation: str) -> str:
    return f"{COMMON_SENSE_SYSTEM_PROMPT}\n\nCONTEXTO:\n{context}\n\nSITUAÇÃO:\n{situation}\n"


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def _contradiction_key(text: str) -> str:
    value = _normalise(text)
    value = re.sub(r"\b(não|nao|sem|nunca|jamais)\b", "", value)
    return " ".join(value.split())


def detect_contradictions(facts: Iterable[Fact]) -> tuple[str, ...]:
    facts = tuple(facts)
    contradictions: list[str] = []
    for index, left in enumerate(facts):
        for right in facts[index + 1:]:
            if _contradiction_key(left.text) != _contradiction_key(right.text):
                continue
            left_negative = bool(re.search(r"\b(não|nao|sem|nunca|jamais)\b", left.text.casefold()))
            right_negative = bool(re.search(r"\b(não|nao|sem|nunca|jamais)\b", right.text.casefold()))
            if left_negative != right_negative:
                contradictions.append(f"fatos contraditórios: '{left.text}' / '{right.text}'")
    return tuple(contradictions)


def validate_result(result: SensemakingResult) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not result.situation.strip():
        errors.append("situação vazia")
    fact_ids = {fact.text for fact in result.facts}
    if len(fact_ids) != len(result.facts):
        warnings.append("fatos duplicados")
    for fact in result.facts:
        if not 0.0 <= fact.confidence <= 1.0:
            errors.append("confidence de fato fora de 0..1")
        if fact.source != "user" and not fact.evidence_refs:
            warnings.append(f"fato sem evidência: {fact.text}")
        for ref in fact.evidence_refs:
            if not _valid_url(ref) and not str(ref).startswith(("memory://", "tasker://", "log://")):
                errors.append(f"evidência inválida: {ref}")
    for inference in result.inferences:
        if not 0.0 <= inference.confidence <= 1.0:
            errors.append("confidence de inferência fora de 0..1")
        if inference.confidence > 0.0 and not inference.basis:
            errors.append("inferência com confiança positiva sem base")
        if inference.confidence >= 0.8 and not inference.assumptions:
            warnings.append("inferência de alta confiança sem premissas explícitas")
    for recommendation in result.recommendations:
        if recommendation.risk in {"high", "critical"} and not recommendation.requires_confirmation:
            errors.append(f"ação sensível sem confirmação: {recommendation.action}")
        if recommendation.risk in {"high", "critical"} and recommendation.reversible:
            warnings.append(f"ação de alto risco marcada como reversível: {recommendation.action}")
    contradictions = detect_contradictions(result.facts)
    if contradictions:
        errors.extend(contradictions)
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


def make_safe_result(situation: str, facts: Iterable[Fact], inferences: Iterable[Inference] = (), risks: Iterable[str] = (), recommendations: Iterable[ActionRecommendation] = (), needs_clarification: Iterable[str] = ()) -> tuple[SensemakingResult, ValidationResult]:
    fact_tuple = tuple(facts)
    result = SensemakingResult(situation, fact_tuple, tuple(inferences), tuple(risks), tuple(recommendations), detect_contradictions(fact_tuple), tuple(needs_clarification))
    return result, validate_result(result)
