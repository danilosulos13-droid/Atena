"""Roteiro curto e factual para áudio de aprendizagem da Atena."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _clip(value: object, limit: int = 420) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _latest(root: Path) -> dict[str, Any]:
    candidates = [
        root / "atena_evolution" / "training" / "latest_workflow_result.json",
        root / "atena_evolution" / "proposals",
    ]
    for path in candidates:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
            except (OSError, json.JSONDecodeError):
                continue
        if path.is_dir():
            files = sorted(path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            for proposal in files:
                try:
                    payload = json.loads(proposal.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        return payload
                except (OSError, json.JSONDecodeError):
                    continue
    return {}


def build_learning_spoken_text(payload: dict[str, Any]) -> str:
    collection = payload.get("collection", {}) if isinstance(payload.get("collection"), dict) else {}
    training = payload.get("training", {}) if isinstance(payload.get("training"), dict) else {}
    observations = payload.get("observations", {}) if isinstance(payload.get("observations"), dict) else {}
    research = payload.get("research", {}) if isinstance(payload.get("research"), dict) else {}
    links = payload.get("research_links", [])
    topic = observations.get("research_plan", {}).get("topic") if isinstance(observations.get("research_plan"), dict) else None
    insights = observations.get("insights", []) or collection.get("insights", []) or []
    risks = observations.get("risks", []) or []
    if not isinstance(insights, list):
        insights = [insights]
    if not isinstance(risks, list):
        risks = [risks]
    lines = [
        "Olá. Aqui é a Atena. Vou explicar o último ciclo de pesquisa e aprendizagem.",
        f"O tema principal pesquisado foi {_clip(topic or 'a evolução geral do sistema', 220)}.",
        f"Foram registradas {len(links) if isinstance(links, list) else 0} "
        f"{'referência' if isinstance(links, list) and len(links) == 1 else 'referências'} de pesquisa.",
    ]
    if insights:
        lines.append("O que eu aprendi ou identifiquei foi: " + " Primeiro: ".join(_clip(item.get("text", item) if isinstance(item, dict) else item, 360) for item in insights[:3]) + ".")
    else:
        lines.append("Neste ciclo não foi registrada uma aprendizagem nova com evidência suficiente.")
    if training:
        status = training.get("status") or training.get("training_status")
        if status:
            lines.append(f"O estado do treinamento foi {status}.")
    if research:
        sources = research.get("sources") or research.get("rss_sources") or []
        if isinstance(sources, list):
            lines.append(f"O relatório consolidou {len(sources)} fontes ou entradas de pesquisa.")
    if risks:
        lines.append("As principais limitações ou riscos são: " + "; ".join(_clip(item, 240) for item in risks[:2]) + ".")
    lines.append("Minha consideração final é que uma informação pesquisada só deve ser tratada como aprendizagem confirmada quando houver fonte, contexto e validação suficiente. Eu posso explicar as evidências e também informar o que ainda não sei.")
    return " ".join(lines)[:3300]


def latest_learning_spoken_text(root: str | Path) -> str:
    return build_learning_spoken_text(_latest(Path(root)))


__all__ = ["build_learning_spoken_text", "latest_learning_spoken_text"]
