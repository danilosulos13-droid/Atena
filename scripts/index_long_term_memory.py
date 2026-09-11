#!/usr/bin/env python3
"""Indexa experiências aprovadas na memória vetorial local, sem alterar pesos do modelo."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "atena_evolution" / "training" / "experiences.jsonl"
INDEXED_IDS = ROOT / "atena_evolution" / "vector_memory" / "indexed_ids.json"


def main() -> int:
    try:
        from core.long_term_memory import LongTermMemory, LongTermMemoryError
        memory = LongTermMemory()
    except Exception as exc:
        print(json.dumps({"status": "skipped", "reason": f"memória vetorial indisponível: {type(exc).__name__}"}))
        return 0
    indexed = 0
    try:
        seen = set(json.loads(INDEXED_IDS.read_text(encoding="utf-8"))) if INDEXED_IDS.exists() else set()
    except (OSError, json.JSONDecodeError, TypeError):
        seen = set()
    if DATASET.exists():
        for line in DATASET.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if float(item.get("score", 0)) < 0.65:
                continue
            experience_id = str(item.get("id", ""))
            if not experience_id or experience_id in seen:
                continue
            text = f"Pergunta: {item.get('prompt', '')}\nResposta: {item.get('response', '')}"
            if text.strip() == "Pergunta: \nResposta:":
                continue
            memory.remember(text, metadata={"source": item.get("source", "unknown"), "experience_id": item.get("id", "")}, tags=["learning"], importance=float(item.get("score", 0.5)))
            seen.add(experience_id)
            indexed += 1
    INDEXED_IDS.parent.mkdir(parents=True, exist_ok=True)
    INDEXED_IDS.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "indexed": indexed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
