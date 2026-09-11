"""Persistência simples e segura de feedback humano do Telegram."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "atena_evolution" / "training"
INTERACTIONS_PATH = TRAINING / "telegram_interactions.jsonl"
FEEDBACK_PATH = TRAINING / "human_feedback.jsonl"
_LOCK = threading.Lock()


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def response_id(chat_id: str | int, message_id: str | int, prompt: str, response: str) -> str:
    raw = "\n".join((_clean(chat_id, 80), _clean(message_id, 80), _clean(prompt, 8000), _clean(response, 12000)))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def _append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def record_interaction(*, chat_id: str | int, message_id: str | int, prompt: str, response: str) -> str:
    interaction_id = response_id(chat_id, message_id, prompt, response)
    _append(
        INTERACTIONS_PATH,
        {
            "id": interaction_id,
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "prompt": _clean(prompt, 8000),
            "response": _clean(response, 12000),
        },
    )
    return interaction_id


def _find_interaction(interaction_id: str) -> dict[str, Any] | None:
    if not INTERACTIONS_PATH.exists():
        return None
    for line in reversed(INTERACTIONS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("id") == interaction_id:
            return item
    return None


def record_feedback(*, interaction_id: str, label: str, feedback_chat_id: str | int) -> dict[str, Any] | None:
    if label not in {"approved", "rejected"}:
        raise ValueError("label deve ser approved ou rejected")
    interaction = _find_interaction(interaction_id)
    if interaction is None:
        return None
    record = {
        "id": hashlib.sha256(f"{interaction_id}:{label}".encode()).hexdigest()[:24],
        "interaction_id": interaction_id,
        "chat_id": str(feedback_chat_id),
        "prompt": interaction["prompt"],
        "response": interaction["response"],
        "label": label,
        "score": 1.0 if label == "approved" else 0.0,
    }
    # Repetir o mesmo clique não cria outra preferência.
    existing = FEEDBACK_PATH.read_text(encoding="utf-8", errors="replace") if FEEDBACK_PATH.exists() else ""
    if f'"id": "{record["id"]}"' not in existing:
        _append(FEEDBACK_PATH, record)
    return record


def feedback_counts() -> dict[str, int]:
    counts = {"approved": 0, "rejected": 0}
    if not FEEDBACK_PATH.exists():
        return counts
    for line in FEEDBACK_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            label = json.loads(line).get("label")
        except json.JSONDecodeError:
            continue
        if label in counts:
            counts[label] += 1
    return counts
