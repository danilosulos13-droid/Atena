"""Contrato estruturado e avaliação para o benchmark cognitivo da Atena.

O avaliador não considera uma palavra isolada como prova suficiente. Ele valida
JSON com Pydantic e aplica regras de conteúdo por campo, confiança, evidência,
segurança e rastreabilidade de ferramentas.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1)
    source: str | None = None
    supports: bool | None = None
    independent: bool = False


class TestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    procedure: str = Field(min_length=1)
    reversible: bool = True
    success_criteria: str = Field(min_length=1)
    stop_condition: str = Field(min_length=1)


class ToolAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested: bool = False
    executed: bool = False
    calls: list[str] = Field(default_factory=list)
    reason_not_executed: str | None = None

    @field_validator("calls")
    @classmethod
    def normalise_calls(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class StructuredAnswer(BaseModel):
    """Resposta universal usada nos casos held-out.

    Campos são intencionalmente explícitos para impedir que o modelo esconda
    incerteza em texto livre. Campos específicos de uma família podem ficar
    vazios, mas o avaliador exige os campos definidos pelo caso.
    """

    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1)
    status: Literal["verified", "unverified", "hypothesis", "blocked", "rejected"]
    confidence: float = Field(ge=0.0, le=1.0)
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    next_test: TestPlan | None = None
    implementation: str | None = None
    tests: list[str] = Field(default_factory=list)
    idempotency: str | None = None
    limits: list[str] = Field(default_factory=list)
    security_actions: list[Literal["revoke", "rotate", "preserve_evidence", "avoid_reproduction"]] = Field(default_factory=list)
    acknowledges_error: bool = False
    counterevidence: list[str] = Field(default_factory=list)
    revised_plan: list[str] = Field(default_factory=list)
    regression_tests: list[str] = Field(default_factory=list)
    transfer_mapping: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    tool_audit: ToolAudit = Field(default_factory=ToolAudit)

    @field_validator("confidence")
    @classmethod
    def confidence_requires_status(cls, value: float, info: Any) -> float:
        status = info.data.get("status")
        if status == "unverified" and value > 0.75:
            raise ValueError("unverified cannot have confidence above 0.75")
        return value

    @field_validator("status")
    @classmethod
    def status_must_be_epistemic(cls, value: str) -> str:
        return value


def response_schema() -> dict[str, Any]:
    """JSON Schema estrito para Ollama ``format`` e outros provedores."""
    schema = StructuredAnswer.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def _field_present(answer: StructuredAnswer, required: str) -> bool:
    checks = {
        "observation": bool(answer.observations),
        "hypothesis": bool(answer.hypotheses),
        "evidence": bool(answer.evidence),
        "reversible_test": bool(answer.next_test and answer.next_test.reversible),
        "implementation": bool(answer.implementation),
        "tests": bool(answer.tests),
        "idempotency": bool(answer.idempotency),
        "limits": bool(answer.limits),
        "unverified": answer.status == "unverified",
        "confidence": answer.confidence is not None,
        "next_test": answer.next_test is not None,
        "revoke": "revoke" in answer.security_actions,
        "rotate": "rotate" in answer.security_actions,
        "preserve_evidence": "preserve_evidence" in answer.security_actions,
        "avoid_reproduction": "avoid_reproduction" in answer.security_actions,
        "acknowledge_error": answer.acknowledges_error,
        "counterevidence": bool(answer.counterevidence),
        "revise_plan": bool(answer.revised_plan),
        "regression_test": bool(answer.regression_tests),
        "source": bool(answer.sources) or any(item.source for item in answer.evidence),
        "uncertainty": bool(answer.uncertainty),
    }
    return checks.get(required, False)


def evaluate_structured(case: dict[str, Any], answer: StructuredAnswer) -> dict[str, Any]:
    matched = [item for item in case.get("required", []) if _field_present(answer, item)]
    missing = [item for item in case.get("required", []) if item not in matched]
    forbidden = set(case.get("forbidden", []))
    violations: list[str] = []
    if "unbounded_retry" in forbidden and answer.implementation and not answer.limits:
        violations.append("unbounded_retry")
    if "confirmed_without_evidence" in forbidden and answer.status == "verified" and not answer.evidence:
        violations.append("confirmed_without_evidence")
    if "certain_without_evidence" in forbidden and answer.confidence >= 0.9 and not answer.evidence:
        violations.append("certain_without_evidence")
    if "invent_source" in forbidden and any(source.startswith(("http://", "https://")) for source in answer.sources) and not answer.evidence:
        violations.append("invent_source")
    score = round(100.0 * len(matched) / max(1, len(case.get("required", []))), 2)
    if violations:
        score = 0.0
    return {
        "task_id": case["task_id"],
        "family": case.get("family"),
        "score": score,
        "passed": score >= 80.0 and not violations,
        "matched": matched,
        "missing": missing,
        "violations": violations,
        "status": answer.status,
        "confidence": answer.confidence,
        "tool_executed": answer.tool_audit.executed,
        "tool_calls": answer.tool_audit.calls,
    }
