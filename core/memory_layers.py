"""Memória em camadas e armazenamento somente aditivo para a Atena.

A camada episódica registra eventos em JSONL append-only. A camada semântica
candidata recebe novas afirmações em arquivos imutáveis. A camada validada só
é criada por uma promoção explícita com evidências e resultado de validação.
Nenhum método reescreve ou apaga registros anteriores.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "memory").casefold()).strip("_")
    return slug[:80] or "memory"


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AppendOnlyMemoryStore:
    """Persistência append-only para memória episódica e semântica.

    O ledger usa append com flush/fsync. Cada candidato e cada promoção têm
    nome derivado do hash do conteúdo e são criados com O_EXCL, portanto um
    registro existente nunca é sobrescrito.
    """

    def __init__(self, root: str | Path = "atena_evolution/memory") -> None:
        self.root = Path(root)
        self.episodic_dir = self.root / "episodic"
        self.semantic_candidates_dir = self.root / "semantic_candidates"
        self.semantic_validated_dir = self.root / "semantic_validated"
        for directory in (self.episodic_dir, self.semantic_candidates_dir, self.semantic_validated_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.episodic_dir / "events.jsonl"

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_json_line(payload))
            handle.flush()
            os.fsync(handle.fileno())

    def append_episodic(self, event: dict[str, Any]) -> dict[str, Any]:
        record = {
            "record_type": "episodic_event",
            "recorded_at": utc_now(),
            **event,
        }
        record["record_id"] = _digest(record)
        self._append(self.ledger_path, record)
        return record

    def _create_immutable_json(self, directory: Path, prefix: str, payload: dict[str, Any]) -> Path:
        record_id = str(payload.get("knowledge_id") or _digest(payload))
        target = directory / f"{_safe_slug(prefix)}_{record_id[:16]}.json"
        if target.exists():
            return target
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return target
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

    def add_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        # A identidade do conhecimento exclui o timestamp para que a mesma
        # evidência não gere candidatos duplicados em ciclos consecutivos.
        identity = {
            "topic": candidate.get("topic", ""),
            "claim": candidate.get("claim", ""),
            "summary": candidate.get("summary", ""),
            "sources": candidate.get("sources", []),
            "evidence": candidate.get("evidence", []),
        }
        payload = {
            "record_type": "semantic_candidate",
            "status": "candidate",
            "created_at": utc_now(),
            **candidate,
        }
        payload["knowledge_id"] = _digest(identity)
        path = self._create_immutable_json(
            self.semantic_candidates_dir,
            str(payload.get("topic", "knowledge")),
            payload,
        )
        event = self.append_episodic({
            "event": "candidate_created",
            "knowledge_id": payload["knowledge_id"],
            "path": str(path),
            "topic": payload.get("topic", ""),
        })
        return {"knowledge_id": payload["knowledge_id"], "path": str(path), "event_id": event["record_id"]}

    def promote_validated(self, knowledge_id: str, validation: dict[str, Any], reviewer: str) -> dict[str, Any]:
        candidates = list(self.semantic_candidates_dir.glob("*.json"))
        source_path: Path | None = None
        source: dict[str, Any] | None = None
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("knowledge_id") == knowledge_id:
                source_path, source = path, data
                break
        if source is None or source_path is None:
            raise FileNotFoundError(f"candidato não encontrado: {knowledge_id}")
        if not validation.get("passed", False):
            raise ValueError("promoção exige validation.passed=true")
        promoted = {
            **source,
            "record_type": "semantic_validated",
            "status": "validated",
            "validated_at": utc_now(),
            "validated_by": reviewer,
            "validation": validation,
        }
        path = self._create_immutable_json(self.semantic_validated_dir, str(source.get("topic", "knowledge")), promoted)
        event = self.append_episodic({
            "event": "candidate_promoted",
            "knowledge_id": knowledge_id,
            "source_candidate": str(source_path),
            "validated_path": str(path),
            "validated_by": reviewer,
        })
        return {"knowledge_id": knowledge_id, "path": str(path), "event_id": event["record_id"]}

    def record_learning_cycle(self, topic: str, payload: dict[str, Any], created: Iterable[dict[str, Any]]) -> dict[str, Any]:
        sources = payload.get("sources", []) if isinstance(payload, dict) else []
        normalized_sources = []
        for item in sources if isinstance(sources, list) else []:
            if isinstance(item, dict):
                normalized_sources.append({
                    key: item.get(key)
                    for key in ("title", "url", "source", "published", "summary")
                    if item.get(key) not in (None, "")
                })
        evidence = [item.get("summary") or item.get("title") for item in normalized_sources if item.get("summary") or item.get("title")]
        candidate = {
            "topic": topic,
            "claim": f"Sinais coletados sobre {topic}",
            "summary": str(payload.get("summary") or payload.get("answer") or ""),
            "sources": normalized_sources,
            "evidence": evidence[:20],
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "uncertainty": ["Ainda não validado por benchmark independente."],
            "validation": {"independent_sources": len({x.get("url") for x in normalized_sources if x.get("url")}), "passed": False},
            "created_assets": list(created),
        }
        candidate_result = self.add_candidate(candidate)
        return {
            "episodic_ledger": str(self.ledger_path),
            "semantic_candidate": candidate_result,
            "source_count": len(normalized_sources),
        }
