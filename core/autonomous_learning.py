#!/usr/bin/env python3
"""Camada de aprendizagem autônoma da ATENA.

Objetivo: fechar o ciclo experiência -> evidência -> dataset -> treino opcional
-> avaliação -> promoção, sem confundir memória/engenharia com treinamento de
pesos. O módulo é seguro por padrão: coleta e preparação são automáticas; treino
só acontece quando explicitamente habilitado por configuração.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
EVOLUTION = ROOT / "atena_evolution"
DATASET_DIR = EVOLUTION / "training"
ARTIFACT_DIR = EVOLUTION / "models"
STATE_FILE = EVOLUTION / "autonomous_learning_state.json"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_id(*parts: str) -> str:
    raw = "\n".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:24]


def _clean(text: Any, limit: int = 12000) -> str:
    return str(text or "").strip()[:limit]


@dataclass
class Experience:
    prompt: str
    response: str
    score: float = 0.0
    source: str = "unknown"
    task_id: str = ""
    topic: str = ""
    evidence: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)

    @property
    def id(self) -> str:
        return stable_id(self.prompt, self.response, self.source)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["id"] = self.id
        return value


class ExperienceLedger:
    """Ledger JSONL idempotente para experiências que podem virar treino."""

    def __init__(self, path: Path = DATASET_DIR / "experiences.jsonl") -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    self._ids.add(str(json.loads(line).get("id", "")))
                except json.JSONDecodeError:
                    continue

    def append(self, experience: Experience) -> bool:
        if not experience.prompt or not experience.response or experience.id in self._ids:
            return False
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(experience.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        self._ids.add(experience.id)
        return True

    def all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                pass
        return rows


def collect_from_learning_memory(ledger: ExperienceLedger) -> int:
    """Converte ciclos de internet em exemplos somente quando há texto útil."""
    path = EVOLUTION / "learning_memory.jsonl"
    if not path.exists():
        return 0
    created = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        # O coletor RSS já converte registros ``internet_research`` por meio
        # de research_to_sft.py; não recatalogar o mesmo artigo semântico aqui.
        if isinstance(item, dict) and item.get("kind") == "internet_research":
            continue
        topic = _clean(item.get("topic"), 1000)
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        candidates = [
            payload.get("answer"), payload.get("response"), payload.get("summary"),
            payload.get("analysis"), item.get("memory"),
        ]
        response = next((_clean(v) for v in candidates if isinstance(v, str) and _clean(v)), "")
        if topic and response and not response.startswith("<coroutine object"):
            created += int(ledger.append(Experience(
                prompt=f"Explique de forma útil e verificável o que foi aprendido sobre: {topic}",
                response=response,
                score=0.65,
                source="background_learning",
                topic=topic,
            )))
    return created


def collect_from_consequence_memory(ledger: ExperienceLedger) -> int:
    """Extrai apenas episódios concluídos com evidência e resultado utilizável."""
    db = EVOLUTION / "consequences.sqlite3"
    if not db.exists():
        return 0
    created = 0
    try:
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT record_json FROM consequence_episodes WHERE outcome IN ('success','partial') ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return 0
    for (raw,) in rows:
        try:
            episode = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        goal = _clean(episode.get("goal"), 4000)
        outcome = _clean(episode.get("outcome_summary"), 6000)
        evidence = episode.get("evidence") or []
        if not goal or not outcome or len(evidence) == 0:
            continue
        score = 0.9 if episode.get("outcome") == "success" else 0.72
        evidence_text = [
            _clean(e.get("claim"), 500) for e in evidence if isinstance(e, dict) and _clean(e.get("claim"))
        ][:8]
        created += int(ledger.append(Experience(
            prompt=f"Resolva a seguinte tarefa com rigor: {goal}",
            response=outcome,
            score=score,
            source="consequence_memory",
            task_id=_clean(episode.get("task_id"), 200),
            evidence=evidence_text,
            created_at=_clean(episode.get("created_at")) or now(),
        )))
    return created


def collect_from_explicit_feedback(ledger: ExperienceLedger) -> int:
    """Aceita datasets externos simples sem depender de uma biblioteca de dados."""
    candidates = [EVOLUTION / "training" / "feedback.jsonl", ROOT / "training" / "feedback.jsonl"]
    created = 0
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            prompt = _clean(item.get("prompt"), 8000)
            chosen = _clean(item.get("chosen") or item.get("response"), 12000)
            if prompt and chosen:
                score = float(item.get("score", 1.0)) if str(item.get("score", "")).strip() else 1.0
                created += int(ledger.append(Experience(prompt, chosen, max(-1, min(1, score)), "explicit_feedback")))
    return created


def build_datasets(ledger: ExperienceLedger, *, min_score: float = 0.65) -> dict[str, int]:
    """Gera SFT e DPO/ORPO-like pares a partir do ledger sem fabricar respostas."""
    rows = [r for r in ledger.all() if _clean(r.get("prompt")) and _clean(r.get("response"))]
    rows = [r for r in rows if float(r.get("score", 0)) >= min_score]
    rows.sort(key=lambda r: (float(r.get("score", 0)), r.get("created_at", "")), reverse=True)
    seen: set[str] = set()
    sft: list[dict[str, Any]] = []
    for row in rows:
        key = stable_id(_clean(row["prompt"]), _clean(row["response"]))
        if key in seen:
            continue
        seen.add(key)
        sft.append({
            "id": row.get("id", key),
            "messages": [
                {"role": "user", "content": _clean(row["prompt"], 8000)},
                {"role": "assistant", "content": _clean(row["response"], 12000)},
            ],
            "score": float(row.get("score", 0)),
            "source": row.get("source", "unknown"),
        })
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    sft_path = DATASET_DIR / "sft.jsonl"
    with sft_path.open("w", encoding="utf-8") as handle:
        for row in sft:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Preferências derivadas de scores diferentes. Não cria rejeições artificiais.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_clean(row["prompt"], 8000), []).append(row)
    preferences: list[dict[str, Any]] = []
    for prompt, group in grouped.items():
        group = sorted(group, key=lambda x: float(x.get("score", 0)), reverse=True)
        if len(group) < 2 or float(group[0].get("score", 0)) <= float(group[-1].get("score", 0)):
            continue
        preferences.append({
            "prompt": prompt,
            "chosen": _clean(group[0]["response"], 12000),
            "rejected": _clean(group[-1]["response"], 12000),
        })
    # Feedback humano tem precedência e pode formar um par mesmo quando a
    # resposta rejeitada não deve entrar no SFT. Só usamos registros explícitos.
    feedback_path = DATASET_DIR / "human_feedback.jsonl"
    human_pairs: dict[str, dict[str, str]] = {}
    if feedback_path.exists():
        for line in feedback_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            prompt = _clean(item.get("prompt"), 8000)
            response = _clean(item.get("response"), 12000)
            label = item.get("label")
            if prompt and response and label in {"approved", "rejected"}:
                pair = human_pairs.setdefault(prompt, {})
                pair[label] = response
    for prompt, pair in human_pairs.items():
        if pair.get("approved") and pair.get("rejected"):
            preferences.append({
                "prompt": prompt,
                "chosen": pair["approved"],
                "rejected": pair["rejected"],
                "source": "human_feedback",
            })
    deduped_preferences: list[dict[str, Any]] = []
    seen_preferences: set[str] = set()
    for preference in preferences:
        key = stable_id(preference["prompt"], preference["chosen"], preference["rejected"])
        if key not in seen_preferences:
            seen_preferences.add(key)
            deduped_preferences.append(preference)
    pref_path = DATASET_DIR / "preferences.jsonl"
    with pref_path.open("w", encoding="utf-8") as handle:
        for row in deduped_preferences:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"experiences": len(rows), "sft": len(sft), "preferences": len(deduped_preferences)}


def write_state(**updates: Any) -> dict[str, Any]:
    current: dict[str, Any] = {}
    if STATE_FILE.exists():
        try:
            current = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current.update(updates)
    current["updated_at"] = now()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def run_collection_cycle() -> dict[str, Any]:
    started = time.perf_counter()
    ledger = ExperienceLedger()
    counts = {
        "learning_memory": collect_from_learning_memory(ledger),
        "consequence_memory": collect_from_consequence_memory(ledger),
        "explicit_feedback": collect_from_explicit_feedback(ledger),
    }
    datasets = build_datasets(ledger)
    result = {
        "status": "ok",
        "collected": counts,
        "datasets": datasets,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    write_state(last_collection=result)
    return result


if __name__ == "__main__":
    print(json.dumps(run_collection_cycle(), ensure_ascii=False, indent=2))
