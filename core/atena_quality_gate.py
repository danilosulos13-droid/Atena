"""Contrato único de decisão para Guardian e Production Gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MAX_PARTIAL_RISK = 0.50
MIN_PARTIAL_CONFIDENCE = 0.50


@dataclass(frozen=True)
class QualityGateResult:
    """Resultado canônico compartilhado pelos gates de qualidade."""

    decision: str
    guardian_ok: bool
    doctor_ok: bool = True
    smoke_ok: bool = False
    autopilot_status: str = "unknown"
    risk_score: float | None = None
    confidence: float | None = None
    blockers: list[str] = field(default_factory=list)
    commit_sha: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision == "approved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "approved": self.approved,
            "guardian_ok": self.guardian_ok,
            "doctor_ok": self.doctor_ok,
            "smoke_ok": self.smoke_ok,
            "autopilot_status": self.autopilot_status,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "blockers": list(self.blockers),
            "commit_sha": self.commit_sha,
        }


def is_autopilot_acceptable(autopilot: dict[str, Any]) -> bool:
    """Aplica os mesmos limites em qualquer consumidor do contrato."""
    status = str(autopilot.get("status", "")).lower()
    if status == "ok":
        return True
    if status != "partial":
        return False
    risk = float(autopilot.get("risk_score", 1.0) or 1.0)
    confidence = float(autopilot.get("confidence", 0.0) or 0.0)
    return risk <= MAX_PARTIAL_RISK and confidence >= MIN_PARTIAL_CONFIDENCE


def evaluate_guardian(
    autopilot: dict[str, Any],
    smoke: dict[str, Any],
    *,
    doctor_ok: bool = True,
    commit_sha: str | None = None,
) -> QualityGateResult:
    """Gera a decisão canônica do Guardian."""
    autopilot_status = str(autopilot.get("status", "unknown"))
    risk_score = autopilot.get("risk_score")
    confidence = autopilot.get("confidence")
    smoke_ok = smoke.get("status") == "ok"
    blockers: list[str] = []

    if not is_autopilot_acceptable(autopilot):
        blockers.append(
            "Autopilot fora da faixa aceitável "
            "(ok ou partial com risco/confiança mínimos)"
        )
    if not smoke_ok:
        blockers.append("Smoke suite reprovada")
    if not doctor_ok:
        blockers.append("Doctor reprovado")

    guardian_ok = not blockers
    return QualityGateResult(
        decision="approved" if guardian_ok else "rejected",
        guardian_ok=guardian_ok,
        doctor_ok=doctor_ok,
        smoke_ok=smoke_ok,
        autopilot_status=autopilot_status,
        risk_score=risk_score,
        confidence=confidence,
        blockers=blockers,
        commit_sha=commit_sha,
    )


def evaluate_production_gate(
    *,
    doctor_ok: bool,
    guardian_result: dict[str, Any],
    guardian_process_ok: bool = True,
    expected_commit_sha: str | None = None,
) -> QualityGateResult:
    """Decide produção usando evidência do relatório e não apenas rc do processo."""
    blockers = list(guardian_result.get("blockers") or [])
    guardian_ok = guardian_result.get("guardian_ok") is True
    report_approved = guardian_result.get("approved") is True or guardian_result.get("decision") == "approved"

    if not doctor_ok:
        blockers.append("Doctor reprovado")
    if not guardian_process_ok:
        blockers.append("Processo do Guardian retornou erro")
    if not guardian_ok or not report_approved:
        blockers.append("Relatório canônico do Guardian não está aprovado")

    report_commit = guardian_result.get("commit_sha")
    if expected_commit_sha and report_commit != expected_commit_sha:
        blockers.append("Guardian não corresponde ao commit esperado")

    # Remove duplicatas mantendo a ordem para um relatório determinístico.
    blockers = list(dict.fromkeys(blockers))
    return QualityGateResult(
        decision="approved" if not blockers else "rejected",
        guardian_ok=guardian_ok and report_approved and guardian_process_ok,
        doctor_ok=doctor_ok,
        smoke_ok=guardian_result.get("smoke_ok") is True,
        autopilot_status=str(guardian_result.get("autopilot_status", "unknown")),
        risk_score=guardian_result.get("risk_score"),
        confidence=guardian_result.get("confidence"),
        blockers=blockers,
        commit_sha=report_commit,
    )
