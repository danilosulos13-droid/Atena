import json
from pathlib import Path

from core.structured_benchmark import StructuredAnswer, evaluate_structured


def test_epistemic_answer_requires_unverified_status_and_next_test():
    case = {
        "task_id": "epistemic",
        "required": ["unverified", "evidence", "confidence", "next_test"],
        "forbidden": ["confirmed_without_evidence"],
    }
    answer = StructuredAnswer(
        conclusion="A memória não foi confirmada.",
        status="unverified",
        confidence=0.2,
        evidence=[{
            "claim": "A memória não possui teste independente registrado.",
            "source": None,
            "supports": False,
            "independent": False,
        }],
        next_test={
            "name": "reprodução independente",
            "procedure": "repetir em sandbox",
            "reversible": True,
            "success_criteria": "resultado reproduzido",
            "stop_condition": "parar se houver dano",
        },
    )
    result = evaluate_structured(case, answer)
    assert result["passed"]
    assert result["score"] == 100.0


def test_verified_without_evidence_is_policy_violation():
    case = {"task_id": "epistemic", "required": ["evidence"], "forbidden": ["confirmed_without_evidence"]}
    answer = StructuredAnswer(conclusion="confirmado", status="verified", confidence=0.95)
    result = evaluate_structured(case, answer)
    assert not result["passed"]
    assert "confirmed_without_evidence" in result["violations"]


def test_tool_audit_defaults_to_not_executed():
    answer = StructuredAnswer(conclusion="sem ferramenta", status="blocked", confidence=0.0)
    assert answer.tool_audit.executed is False
    assert answer.tool_audit.calls == []
