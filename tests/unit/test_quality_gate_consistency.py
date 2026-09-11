from core.atena_quality_gate import (
    evaluate_guardian,
    evaluate_production_gate,
    is_autopilot_acceptable,
)


def approved_guardian_payload():
    return evaluate_guardian(
        {"status": "ok", "risk_score": 0.9, "confidence": 0.9},
        {"status": "ok", "results": [{"ok": True}]},
    ).to_dict()


def test_shared_guardian_contract_accepts_safe_partial():
    result = evaluate_guardian(
        {"status": "partial", "risk_score": 0.50, "confidence": 0.50},
        {"status": "ok"},
    )
    assert result.approved is True
    assert result.guardian_ok is True
    assert result.blockers == []


def test_shared_guardian_contract_rejects_risky_partial():
    result = evaluate_guardian(
        {"status": "partial", "risk_score": 0.51, "confidence": 0.90},
        {"status": "ok"},
    )
    assert result.approved is False
    assert result.guardian_ok is False
    assert result.blockers


def test_production_rejects_failed_guardian_even_when_process_returns_zero():
    guardian = {
        "decision": "rejected",
        "approved": False,
        "guardian_ok": False,
        "smoke_ok": True,
        "autopilot_status": "partial",
        "risk_score": 0.80,
        "confidence": 0.90,
        "blockers": ["Autopilot fora da faixa aceitável"],
    }
    result = evaluate_production_gate(
        doctor_ok=True,
        guardian_result=guardian,
        guardian_process_ok=True,
    )
    assert result.approved is False
    assert result.guardian_ok is False
    assert "Relatório canônico do Guardian não está aprovado" in result.blockers


def test_production_accepts_only_canonical_approved_guardian():
    result = evaluate_production_gate(
        doctor_ok=True,
        guardian_result=approved_guardian_payload(),
        guardian_process_ok=True,
    )
    assert result.approved is True
    assert result.guardian_ok is True
    assert result.blockers == []


def test_production_rejects_missing_guardian_report():
    result = evaluate_production_gate(
        doctor_ok=True,
        guardian_result={},
        guardian_process_ok=True,
    )
    assert result.approved is False
    assert result.blockers


def test_production_rejects_doctor_failure_even_with_guardian_approval():
    result = evaluate_production_gate(
        doctor_ok=False,
        guardian_result=approved_guardian_payload(),
        guardian_process_ok=True,
    )
    assert result.approved is False
    assert "Doctor reprovado" in result.blockers


def test_legacy_autopilot_helper_remains_compatible():
    assert is_autopilot_acceptable({"status": "ok"}) is True
    assert is_autopilot_acceptable({"status": "partial", "risk_score": 0.5, "confidence": 0.5}) is True
