"""Gates determinísticos para validar saídas de ciclos de evolução."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class GateResult:
    accepted: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]

    @property
    def passed(self) -> bool:
        """Alias legado para consumidores antigos; o contrato canônico é ``accepted``."""
        return self.accepted

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_http_url(value: object) -> bool:
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _is_evidence_ref(value: object) -> bool:
    """Aceita URLs e IDs internos gerados pelo armazenamento de evidências."""
    ref = str(value or "").strip()
    return bool(ref) and (_is_http_url(ref) or ref.startswith(("mem-", "rss:", "source:", "tool://")))


def evaluate_cycle(observations: dict[str, Any], *, min_evidence: int = 1, max_duplicate_ratio: float = 0.5) -> GateResult:
    reasons: list[str] = []
    insights = observations.get("insights", [])
    risks = observations.get("risks", [])
    proposals = observations.get("proposed_changes", [])
    next_cycle = observations.get("next_cycle", [])
    if not isinstance(insights, list) or not isinstance(risks, list) or not isinstance(proposals, list) or not isinstance(next_cycle, list):
        return GateResult(False, ("schema de observações inválido",), {})
    if not insights and not risks and not proposals:
        reasons.append("ciclo sem aprendizagem: nenhuma observação, risco ou proposta foi gerada")

    texts: list[str] = []
    evidence_refs = 0
    limitation_without_evidence = 0
    for item in insights:
        if not isinstance(item, dict):
            reasons.append("insight não estruturado")
            continue
        text = " ".join(str(item.get("text", "")).casefold().split())
        if text:
            texts.append(text)
        refs = item.get("evidence_refs", []) or []
        valid_refs = [ref for ref in refs if _is_evidence_ref(ref)] if isinstance(refs, list) else []
        evidence_refs += len(valid_refs)
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not 0.0 <= confidence <= 1.0:
            reasons.append("confidence fora do intervalo 0..1")
        if not valid_refs and confidence > 0.0:
            limitation_without_evidence += 1

    unique_texts = set(texts)
    duplicate_ratio = 0.0 if not texts else 1.0 - len(unique_texts) / len(texts)
    if limitation_without_evidence:
        reasons.append("insight com confidence positiva sem evidência válida")
    if evidence_refs < min_evidence and insights:
        reasons.append("evidência insuficiente para o ciclo")
    if duplicate_ratio > max_duplicate_ratio:
        reasons.append("taxa de insights repetidos acima do limite")
    if any("crítico" in str(r).casefold() or "critical" in str(r).casefold() for r in risks):
        reasons.append("risco crítico presente; exige revisão humana")
    if insights and not next_cycle:
        reasons.append("insights sem próximo teste ou plano de verificação")

    metrics = {
        "insights": len(insights),
        "evidence_refs": evidence_refs,
        "duplicate_ratio": round(duplicate_ratio, 4),
        "proposals": len(proposals),
        "risks": len(risks),
    }
    return GateResult(not reasons, tuple(reasons), metrics)
