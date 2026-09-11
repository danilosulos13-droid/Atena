from core.sensemaking import (
    ActionRecommendation,
    Fact,
    Inference,
    build_prompt,
    detect_contradictions,
    make_safe_result,
    validate_result,
)


def test_prompt_demands_fact_inference_separation():
    prompt = build_prompt("telefone recebeu chuva", "o que fazer?")
    assert "Separe rigorosamente" in prompt
    assert "Retorne apenas JSON" in prompt


def test_detects_negated_fact_contradiction():
    facts = (Fact("o telefone está molhado"), Fact("o telefone não está molhado"))
    contradictions = detect_contradictions(facts)
    assert contradictions


def test_inference_requires_basis():
    result, validation = make_safe_result(
        "situação",
        [Fact("há água no aparelho")],
        [Inference("pode haver dano elétrico", confidence=0.8)],
    )
    assert not validation.valid
    assert any("base" in error for error in validation.errors)


def test_sensitive_recommendation_requires_confirmation():
    result, validation = make_safe_result(
        "situação",
        [Fact("o usuário pediu ação")],
        recommendations=[ActionRecommendation("enviar mensagem", "pedido do usuário", risk="high")],
    )
    assert not validation.valid
    assert any("confirmação" in error for error in validation.errors)


def test_supported_result_is_valid():
    result, validation = make_safe_result(
        "telefone molhado",
        [Fact("o telefone recebeu água", source="user")],
        [Inference("não ligar imediatamente", basis=("o telefone recebeu água",), assumptions=("há umidade interna possível",), confidence=0.7, uncertainty="a extensão do dano é desconhecida")],
        risks=["possível dano elétrico"],
        recommendations=[ActionRecommendation("desligar e secar externamente", "reduzir risco", risk="low")],
        needs_clarification=["o aparelho está ligado?"]
    )
    assert validation.valid
