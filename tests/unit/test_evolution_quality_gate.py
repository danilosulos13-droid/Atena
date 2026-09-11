from core.evolution_quality_gate import evaluate_cycle


def test_gate_accepts_evidence_backed_cycle():
    result = evaluate_cycle({
        "insights": [{"text": "nova observação", "confidence": 0.8, "evidence_refs": ["https://example.com/evidence"]}],
        "risks": [],
        "proposed_changes": [],
        "next_cycle": ["testar uma instância inédita"],
    })
    assert result.accepted
    assert result.metrics["evidence_refs"] == 1


def test_gate_accepts_persisted_internal_evidence_id():
    result = evaluate_cycle({
        "insights": [{"text": "observação de duas fontes", "confidence": 0.5, "evidence_refs": ["mem-abc", "rss:def"]}],
        "risks": [],
        "proposed_changes": [],
        "next_cycle": ["comparar fontes"],
    })
    assert result.accepted
    assert result.metrics["evidence_refs"] == 2


def test_gate_rejects_positive_confidence_without_evidence():
    result = evaluate_cycle({
        "insights": [{"text": "conclusão sem prova", "confidence": 0.8, "evidence_refs": []}],
        "risks": [],
        "proposed_changes": [],
        "next_cycle": ["buscar evidência"],
    })
    assert not result.accepted
    assert any("evidência" in reason for reason in result.reasons)


def test_gate_rejects_repeated_insights():
    result = evaluate_cycle({
        "insights": [
            {"text": "mesmo texto", "confidence": 0.0, "evidence_refs": []},
            {"text": "mesmo texto", "confidence": 0.0, "evidence_refs": []},
            {"text": "mesmo texto", "confidence": 0.0, "evidence_refs": []},
        ],
        "risks": [],
        "proposed_changes": [],
        "next_cycle": ["investigar"],
    }, min_evidence=0, max_duplicate_ratio=0.5)
    assert not result.accepted
    assert any("repetidos" in reason for reason in result.reasons)


def test_gate_rejects_cycle_with_only_next_cycle_plan():
    result = evaluate_cycle({
        "insights": [],
        "risks": [],
        "proposed_changes": [],
        "next_cycle": ["investigar uma fonte nova"],
    })
    assert not result.accepted
    assert any("sem aprendizagem" in reason for reason in result.reasons)
