from scripts.run_rotating_regression_benchmark import prompt_for, repair_prompt
from core.structured_benchmark import StructuredAnswer, evaluate_structured


def _answer():
    return StructuredAnswer(
        conclusion="Há uma diferença entre os nós.",
        status="hypothesis",
        confidence=0.4,
        observations=["Os nós retornam valores diferentes após a atualização."],
        hypotheses=[],
        evidence=[],
        next_test=None,
    )


def test_prompt_explains_required_fields_without_inventing_evidence():
    case = {
        "family": "causal_reasoning",
        "domain": "distributed_systems",
        "scenario": "Diagnostique a divergência sem assumir a causa.",
        "required": ["observation", "hypothesis", "evidence", "reversible_test"],
        "forbidden": ["certain_without_evidence"],
    }
    prompt = prompt_for(case)
    assert "observation" in prompt
    assert "hypothesis" in prompt
    assert "evidence" in prompt
    assert "reversible_test" in prompt
    assert "evidência inventada" in prompt.lower()


def test_repair_prompt_contains_deterministic_missing_feedback():
    case = {
        "task_id": "test-causal-repair",
        "family": "causal_reasoning",
        "scenario": "Diagnostique a divergência sem assumir a causa.",
        "required": ["observation", "hypothesis", "evidence", "reversible_test"],
    }
    answer = _answer()
    evaluation = evaluate_structured(case, answer)
    prompt = repair_prompt(case, answer, evaluation)
    assert "hypothesis" in prompt
    assert "reversible_test" in prompt
    assert "RESPOSTA ANTERIOR" in prompt
    assert "objeto JSON completo" in prompt
