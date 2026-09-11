"""Contrato e utilitários para memória episódica auditável da Atena.

O módulo é deliberadamente independente de SQLite e de FAISS. Ele define o
registro canônico que pode ser serializado, validado, hasheado e transportado
entre armazenamento, benchmarks e índices derivados.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "1.0"
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
VALID_RECORD_TYPES = {"observation", "action", "outcome", "failure", "hypothesis"}
VALID_STATUSES = {"unverified", "supported", "confirmed", "refuted", "contested"}
VALID_LIFECYCLE_STATES = {"active", "superseded", "expired", "quarantined"}
VALID_SOURCE_TYPES = {"user", "benchmark", "llm", "tool", "workflow", "human_review", "external_source"}


class EpisodicMemoryError(ValueError):
    """Erro de contrato, integridade ou proveniência de um episódio."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    """Serializa JSON de maneira determinística para hashing."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EpisodicMemoryError(f"valor não é canonicalizável: {exc}") from exc


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _hash_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(record))
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("content_hash", None)
    payload.pop("content_hash", None)
    return payload


def compute_content_hash(record: Mapping[str, Any]) -> str:
    """Calcula o hash sem incluir o hash armazenado no próprio registro."""
    return sha256_digest(_hash_payload(record))


def make_memory_id(created_at: str | None = None, seed: str | None = None) -> str:
    timestamp = (created_at or utc_now()).replace("-", "").replace(":", "").replace("+", "").replace("Z", "")
    timestamp = timestamp.replace("T", "")[:14]
    suffix = hashlib.sha256((seed or timestamp).encode("utf-8")).hexdigest()[:12]
    return f"mem-{timestamp}-{suffix}"


def _require_string(obj: Mapping[str, Any], key: str, path: str = "") -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EpisodicMemoryError(f"{path + '.' if path else ''}{key} deve ser texto não vazio")
    return value


def validate_record(record: Mapping[str, Any], verify_hash: bool = True) -> dict[str, Any]:
    """Valida e retorna uma cópia normalizada do registro episódico."""
    if not isinstance(record, Mapping):
        raise EpisodicMemoryError("episódio deve ser um objeto JSON")
    value = deepcopy(dict(record))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise EpisodicMemoryError("schema_version não suportada")
    for key in ("memory_id", "record_type", "created_at", "provenance", "subject", "event", "evidence", "lifecycle"):
        if key not in value:
            raise EpisodicMemoryError(f"campo obrigatório ausente: {key}")
    if value["record_type"] not in VALID_RECORD_TYPES:
        raise EpisodicMemoryError("record_type inválido")
    _require_string(value, "memory_id")
    _require_string(value, "created_at")
    try:
        datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise EpisodicMemoryError("created_at deve estar em ISO-8601") from exc

    provenance = value["provenance"]
    subject = value["subject"]
    event = value["event"]
    evidence = value["evidence"]
    lifecycle = value["lifecycle"]
    for name, obj in (("provenance", provenance), ("subject", subject), ("event", event), ("evidence", evidence), ("lifecycle", lifecycle)):
        if not isinstance(obj, dict):
            raise EpisodicMemoryError(f"{name} deve ser objeto")

    source_type = _require_string(provenance, "source_type", "provenance")
    if source_type not in VALID_SOURCE_TYPES:
        raise EpisodicMemoryError("provenance.source_type inválido")
    _require_string(provenance, "source_id", "provenance")
    _require_string(provenance, "system_version", "provenance")
    _require_string(subject, "task_id", "subject")
    _require_string(subject, "domain", "subject")
    _require_string(event, "input_digest", "event")
    if not isinstance(event.get("output"), str):
        raise EpisodicMemoryError("event.output deve ser texto")

    status = evidence.get("status")
    confidence = evidence.get("confidence")
    if status not in VALID_STATUSES:
        raise EpisodicMemoryError("evidence.status inválido")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise EpisodicMemoryError("evidence.confidence deve estar entre 0 e 1")
    if not isinstance(evidence.get("refs", []), list) or not all(isinstance(x, str) for x in evidence.get("refs", [])):
        raise EpisodicMemoryError("evidence.refs deve ser lista de textos")

    if lifecycle.get("state") not in VALID_LIFECYCLE_STATES:
        raise EpisodicMemoryError("lifecycle.state inválido")
    if not isinstance(lifecycle.get("retention_class"), str):
        raise EpisodicMemoryError("lifecycle.retention_class ausente")

    actual = value.get("content_hash") or provenance.get("content_hash")
    if actual is None:
        actual = compute_content_hash(value)
        value["content_hash"] = actual
        provenance["content_hash"] = actual
    if not isinstance(actual, str) or not HASH_PATTERN.fullmatch(actual):
        raise EpisodicMemoryError("content_hash inválido")
    if verify_hash and actual != compute_content_hash(value):
        raise EpisodicMemoryError("content_hash não corresponde ao conteúdo")
    if provenance.get("content_hash") not in (None, actual):
        raise EpisodicMemoryError("hash duplicado na raiz e na proveniência diverge")
    provenance["content_hash"] = actual
    value["content_hash"] = actual
    return value


@dataclass(frozen=True)
class EpisodeRecord:
    memory_id: str
    record_type: str
    created_at: str
    provenance: dict[str, Any]
    subject: dict[str, Any]
    event: dict[str, Any]
    evidence: dict[str, Any]
    lifecycle: dict[str, Any]
    privacy: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return validate_record(value, verify_hash=self.content_hash is not None)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], verify_hash: bool = True) -> "EpisodeRecord":
        checked = validate_record(value, verify_hash=verify_hash)
        return cls(**checked)


def verify_hash_chain(records: Iterable[Mapping[str, Any]]) -> str | None:
    """Verifica a cadeia na ordem fornecida e retorna o último hash."""
    previous: str | None = None
    for index, raw in enumerate(records):
        record = validate_record(raw)
        linked = record["provenance"].get("previous_record_hash")
        if linked != previous:
            raise EpisodicMemoryError(
                f"quebra da cadeia na posição {index}: esperado={previous}, recebido={linked}"
            )
        previous = record["content_hash"]
    return previous


def build_episode(
    *,
    record_type: str,
    task_id: str,
    domain: str,
    output: str,
    source_type: str,
    source_id: str,
    system_version: str,
    source_url: str | None = None,
    model: str | None = None,
    confidence: float = 0.0,
    status: str = "unverified",
    previous_record_hash: str | None = None,
    evidence_refs: list[str] | None = None,
    event_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_at = utc_now()
    record: dict[str, Any] = {
        "memory_id": make_memory_id(created_at, f"{source_id}:{output}"),
        "schema_version": SCHEMA_VERSION,
        "record_type": record_type,
        "created_at": created_at,
        "provenance": {
            "source_type": source_type,
            "source_id": source_id,
            "source_url": source_url,
            "model": model,
            "system_version": system_version,
            "parent_memory_ids": [],
            "previous_record_hash": previous_record_hash,
        },
        "subject": {"task_id": task_id, "domain": domain, "benchmark_version": None, "capability": None},
        "event": {
            "input_digest": sha256_digest({"task_id": task_id, "source_id": source_id}),
            "output": output,
            "output_redacted": False,
            "environment": {},
            **(event_extra or {}),
        },
        "evidence": {
            "status": status,
            "confidence": confidence,
            "refs": evidence_refs or [],
            "counterevidence_refs": [],
            "verification_method": None,
        },
        "lifecycle": {"state": "active", "retention_class": "raw", "supersedes": None},
        "privacy": {"redactions": [], "contains_secret": False},
    }
    record["content_hash"] = compute_content_hash(record)
    record["provenance"]["content_hash"] = record["content_hash"]
    return validate_record(record)
