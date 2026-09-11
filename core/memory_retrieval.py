"""Recuperação lexical e epistemológica de episódios SQLite para os ciclos da Atena."""
from __future__ import annotations
import json, math, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from core.memory_store import MemoryStore

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]{3,}", re.UNICODE)
_STOP = {"para", "com", "sem", "sobre", "como", "uma", "que", "dos", "das", "por", "não", "na", "no", "nos", "nas"}

def _tokens(text: str) -> set[str]:
    return {t.casefold() for t in _TOKEN_RE.findall(text) if t.casefold() not in _STOP}

def _episode_text(record: dict[str, Any]) -> str:
    event = record.get("event", {})
    output = event.get("output", "") if isinstance(event, dict) else ""
    return " ".join([str(record.get("subject", {}).get("domain", "")), str(record.get("subject", {}).get("task_id", "")), str(output)])

def _recency_score(created_at: str) -> float:
    try:
        value = created_at.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds() / 86400)
        return math.exp(-age_days / 30.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def retrieve_context(db_path: str | Path, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Retorna episódios relevantes sem modificar a memória append-only.

    O ranking combina correspondência textual, confiança, evidência e recência.
    A memória não é alterada durante a recuperação.
    """
    wanted = _tokens(query)
    if not wanted:
        return []
    with MemoryStore(db_path) as store:
        rows = store.connection.execute(
            "SELECT id, record_json, created_at, status, confidence, lifecycle_state FROM episodes "
            "WHERE lifecycle_state NOT IN ('superseded','expired') ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        scored = []
        for row in rows:
            record = json.loads(row[1]); tokens = _tokens(_episode_text(record)); overlap = len(wanted & tokens)
            if overlap == 0: continue
            lexical = overlap / math.sqrt(max(1, len(wanted) * len(tokens)))
            item = {"episode_id": row[0], "created_at": row[2], "status": row[3], "confidence": row[4], "score": round(lexical, 5), "record": record}
            try: item["evidence"] = store.evidence_summary(row[0])
            except Exception: item["evidence"] = {"status": "unverified"}
            evidence = item["evidence"] or {}
            evidence_count = int(evidence.get("count", evidence.get("evidence_count", 0)) or 0)
            verified = 1.0 if str(evidence.get("status", row[3])).casefold() in {"verified", "supported", "confirmed"} else 0.0
            confidence = max(0.0, min(1.0, float(row[4] or 0.0)))
            recency = _recency_score(str(row[2]))
            item["ranking"] = round(0.65 * lexical + 0.15 * confidence + 0.10 * min(1.0, evidence_count / 3) + 0.05 * verified + 0.05 * recency, 5)
            scored.append(item)
        scored.sort(key=lambda x: (x["ranking"], x["score"], x["created_at"]), reverse=True)
        return scored[:max(1, min(int(limit), 50))]

def format_context(items: list[dict[str, Any]], max_chars: int = 9000) -> str:
    """Formata contexto com IDs, status e evidência para o prompt do modelo."""
    chunks=[]; used=0
    for item in items:
        record=item["record"]; output=record.get("event", {}).get("output", "")
        chunk = json.dumps({"episode_id": item["episode_id"], "created_at": item["created_at"], "status": item["status"], "confidence": item["confidence"], "evidence": item.get("evidence", {}), "output": output[:1800]}, ensure_ascii=False)
        if used + len(chunk) > max_chars: break
        chunks.append(chunk); used += len(chunk)
    return "\n".join(chunks) if chunks else "(nenhum episódio SQLite relevante recuperado)"
