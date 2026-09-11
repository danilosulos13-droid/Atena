#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATENA Aegis Mythos Challenger
Benchmark estratégico: posição competitiva da ATENA frente a modelos frontier
(referência Mythos) em segurança operacional, auditabilidade e roteamento defensivo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "analysis_reports"

_DIMENSIONS = [
    "security_operacional",
    "auditabilidade",
    "roteamento_agentes_defensivos",
    "resiliencia_falhas",
    "governanca_politicas",
    "auto_correcao",
    "latencia_decisao",
    "cobertura_testes",
]

_ATENA_BASELINE: dict[str, float] = {
    "security_operacional": 0.82,
    "auditabilidade": 0.78,
    "roteamento_agentes_defensivos": 0.85,
    "resiliencia_falhas": 0.80,
    "governanca_politicas": 0.75,
    "auto_correcao": 0.88,
    "latencia_decisao": 0.79,
    "cobertura_testes": 0.72,
}

_MYTHOS_REFERENCE: dict[str, float] = {
    "security_operacional": 0.91,
    "auditabilidade": 0.89,
    "roteamento_agentes_defensivos": 0.87,
    "resiliencia_falhas": 0.90,
    "governanca_politicas": 0.86,
    "auto_correcao": 0.84,
    "latencia_decisao": 0.93,
    "cobertura_testes": 0.88,
}


def _composite(scores: dict[str, float]) -> float:
    vals = list(scores.values())
    return round(sum(vals) / max(1, len(vals)), 4)


def _release_decision(atena: float, mythos: float) -> str:
    delta = mythos - atena
    if delta <= 0:
        return "GO — ATENA supera referência"
    elif delta <= 0.05:
        return "GO_WITH_WARNINGS — diferença mínima, monitorar"
    elif delta <= 0.10:
        return "CONDITIONAL — melhorias prioritárias necessárias"
    else:
        return "NO_GO — gap significativo, requer sprint de melhoria"


_ACTION_MAP = {
    "security_operacional": "Implementar scanning de secrets em CI, RBAC granular e auditoria de acessos",
    "auditabilidade": "Adicionar logging estruturado com correlation_id em todos os módulos core",
    "roteamento_agentes_defensivos": "Expandir AtenaLLMRouter com políticas de failover e circuit-breaker",
    "resiliencia_falhas": "Adicionar retry exponencial, bulkhead pattern e chaos tests",
    "governanca_politicas": "Criar policy engine com regras declarativas e auditoria automática",
    "auto_correcao": "Aprimorar selfmod_engine_v2 com validação semântica e rollback automático",
    "latencia_decisao": "Otimizar hot-path do LLM router com cache L1/L2 e pré-aquecimento",
    "cobertura_testes": "Elevar cobertura para 85%+ com testes de integração e mutation testing",
}


class AegisMythosChallenger:
    """Analisa posição competitiva da ATENA e gera plano estratégico."""

    def __init__(
        self,
        atena_scores: dict[str, float] | None = None,
        mythos_scores: dict[str, float] | None = None,
    ) -> None:
        self.atena_scores = atena_scores or _ATENA_BASELINE.copy()
        self.mythos_scores = mythos_scores or _MYTHOS_REFERENCE.copy()

    def build_plan(self, objective: str = "") -> dict[str, Any]:
        objective = objective or "superar Mythos em segurança operacional, auditabilidade e roteamento"

        gaps = {
            dim: self.mythos_scores.get(dim, 0.85) - self.atena_scores.get(dim, 0.75)
            for dim in _DIMENSIONS
        }

        atena_composite = _composite(self.atena_scores)
        mythos_composite = _composite(self.mythos_scores)
        delta = round(mythos_composite - atena_composite, 4)
        decision = _release_decision(atena_composite, mythos_composite)

        action_plan = []
        for dim, gap in sorted(gaps.items(), key=lambda x: x[1], reverse=True):
            if gap <= 0:
                continue
            priority = "P0" if gap > 0.10 else ("P1" if gap > 0.05 else "P2")
            action_plan.append({
                "dimensao": dim,
                "gap": round(gap, 4),
                "prioridade": priority,
                "acao": _ACTION_MAP.get(dim, f"Revisar módulo {dim}"),
                "esforco_estimado": "alta" if gap > 0.10 else ("media" if gap > 0.05 else "baixa"),
            })

        positive_gaps = [g for g in gaps.values() if g > 0]
        confidence = round(1.0 - (sum(positive_gaps) / (len(_DIMENSIONS) * 0.2 + 1e-9)), 3)
        confidence = max(0.0, min(1.0, confidence))

        status = "ok" if delta <= 0.05 else ("warning" if delta <= 0.10 else "critical")

        return {
            "objective": objective,
            "status": status,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "benchmark": {
                "atena_composite": atena_composite,
                "mythos_composite": mythos_composite,
                "target_delta": delta,
                "release_decision": decision,
                "confidence": confidence,
                "dimension_scores": {
                    dim: {
                        "atena": self.atena_scores.get(dim),
                        "mythos": self.mythos_scores.get(dim),
                        "gap": round(gaps[dim], 4),
                    }
                    for dim in _DIMENSIONS
                },
            },
            "action_plan": action_plan,
            "claim_boundary": (
                f"ATENA composite: {atena_composite:.3f} | "
                f"Mythos reference: {mythos_composite:.3f} | "
                f"Delta: {delta:+.3f} | "
                f"Confidence: {confidence:.3f}"
            ),
            "total_actions": len(action_plan),
            "p0_actions": sum(1 for a in action_plan if a["prioridade"] == "P0"),
        }


def write_reports(payload: dict[str, Any], output_dir: Path | None = None) -> tuple[Path, Path]:
    """Escreve relatórios JSON e Markdown. Retorna (json_path, md_path)."""
    out = output_dir or REPORTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    json_path = out / f"ATENA_Aegis_Mythos_{ts}.json"
    md_path = out / f"ATENA_Aegis_Mythos_{ts}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    bench = payload.get("benchmark", {})
    action_plan = payload.get("action_plan", [])
    status = payload.get("status", "").upper()
    indicator = "🟢" if status == "OK" else ("🟡" if status == "WARNING" else "🔴")

    lines = [
        f"# ATENA Aegis Mythos Challenger — {ts}",
        "",
        f"**Objetivo:** {payload.get('objective', '')}",
        f"**Status:** {indicator} {status}",
        "",
        "## Benchmark",
        "",
        "| Métrica | Valor |",
        "|---------|-------|",
        f"| ATENA Composite | `{bench.get('atena_composite', 0):.4f}` |",
        f"| Mythos Reference | `{bench.get('mythos_composite', 0):.4f}` |",
        f"| Delta | `{bench.get('target_delta', 0):+.4f}` |",
        f"| Decisão | {bench.get('release_decision', '')} |",
        f"| Confidence | `{bench.get('confidence', 0):.3f}` |",
        "",
        "## Dimensões",
        "",
        "| Dimensão | ATENA | Mythos | Gap |",
        "|----------|-------|--------|-----|",
    ]

    for dim, vals in bench.get("dimension_scores", {}).items():
        gap = vals.get("gap", 0)
        ind = "🔴" if gap > 0.10 else ("🟡" if gap > 0.05 else "🟢")
        lines.append(f"| {dim} | `{vals.get('atena', 0):.3f}` | `{vals.get('mythos', 0):.3f}` | {ind} `{gap:+.3f}` |")

    lines += ["", "## Plano de Ação", ""]
    for action in action_plan:
        lines += [
            f"### [{action['prioridade']}] {action['dimensao']}",
            f"- **Gap:** `{action['gap']:+.4f}`",
            f"- **Ação:** {action['acao']}",
            f"- **Esforço:** {action['esforco_estimado']}",
            "",
        ]

    lines += ["---", f"*{payload.get('claim_boundary', '')}*"]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return json_path, md_path
