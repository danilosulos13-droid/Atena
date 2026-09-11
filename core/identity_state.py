"""Identidade e estado persistente da Atena com integridade verificável.

Este módulo guarda somente estado operacional e preferências autorizadas. Não
trata o modelo como pessoa nem cria afirmações de consciência; mantém coerência
entre sessões e registra transições auditáveis.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_state (
    identity_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    commitments_json TEXT NOT NULL DEFAULT '[]',
    current_state TEXT NOT NULL DEFAULT 'idle',
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identity_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_identity_events_identity ON identity_events(identity_id, event_id);
"""


@dataclass(frozen=True)
class IdentitySnapshot:
    identity_id: str
    display_name: str
    preferences: dict[str, Any]
    commitments: list[str]
    current_state: str
    version: int
    updated_at: str
    content_hash: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload).encode()).hexdigest()


class IdentityStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "IdentityStateStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, identity_id: str) -> IdentitySnapshot | None:
        row = self.connection.execute("SELECT * FROM identity_state WHERE identity_id=?", (identity_id,)).fetchone()
        if row is None:
            return None
        snapshot = IdentitySnapshot(
            identity_id=str(row["identity_id"]),
            display_name=str(row["display_name"]),
            preferences=json.loads(row["preferences_json"]),
            commitments=json.loads(row["commitments_json"]),
            current_state=str(row["current_state"]),
            version=int(row["version"]),
            updated_at=str(row["updated_at"]),
            content_hash=str(row["content_hash"]),
        )
        if snapshot.content_hash != self._snapshot_hash(snapshot):
            raise ValueError(f"hash de identidade inválido: {identity_id}")
        return snapshot

    @staticmethod
    def _snapshot_hash(snapshot: IdentitySnapshot) -> str:
        payload = asdict(snapshot)
        payload.pop("content_hash", None)
        return _digest(payload)

    def upsert(self, identity_id: str, *, display_name: str = "", preferences: dict[str, Any] | None = None, commitments: list[str] | None = None, current_state: str = "idle", expected_version: int | None = None) -> IdentitySnapshot:
        current = self.get(identity_id)
        if expected_version is not None and (current is None or current.version != expected_version):
            raise RuntimeError("conflito de versão da identidade")
        version = 0 if current is None else current.version + 1
        snapshot = IdentitySnapshot(identity_id, display_name, preferences or {}, commitments or [], current_state, version, _now(), "")
        snapshot = IdentitySnapshot(**{**asdict(snapshot), "content_hash": self._snapshot_hash(snapshot)})
        with self.connection:
            self.connection.execute(
                "INSERT INTO identity_state VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(identity_id) DO UPDATE SET display_name=excluded.display_name, preferences_json=excluded.preferences_json, commitments_json=excluded.commitments_json, current_state=excluded.current_state, version=excluded.version, updated_at=excluded.updated_at, content_hash=excluded.content_hash",
                (snapshot.identity_id, snapshot.display_name, _canonical(snapshot.preferences), _canonical(snapshot.commitments), snapshot.current_state, snapshot.version, snapshot.updated_at, snapshot.content_hash),
            )
        return snapshot

    def append_event(self, identity_id: str, event_type: str, payload: dict[str, Any]) -> str:
        previous = self.connection.execute("SELECT content_hash FROM identity_events WHERE identity_id=? ORDER BY event_id DESC LIMIT 1", (identity_id,)).fetchone()
        previous_hash = str(previous[0]) if previous else None
        created_at = _now()
        content_hash = _digest({"identity_id": identity_id, "event_type": event_type, "payload": payload, "previous_hash": previous_hash, "created_at": created_at})
        with self.connection:
            self.connection.execute("INSERT INTO identity_events(identity_id,event_type,payload_json,previous_hash,content_hash,created_at) VALUES (?,?,?,?,?,?)", (identity_id, event_type, _canonical(payload), previous_hash, content_hash, created_at))
        return content_hash

    def verify_events(self, identity_id: str) -> str | None:
        rows = self.connection.execute("SELECT * FROM identity_events WHERE identity_id=? ORDER BY event_id", (identity_id,)).fetchall()
        previous = None
        for row in rows:
            if row["previous_hash"] != previous:
                raise ValueError("quebra da cadeia de eventos de identidade")
            expected = _digest({"identity_id": row["identity_id"], "event_type": row["event_type"], "payload": json.loads(row["payload_json"]), "previous_hash": row["previous_hash"], "created_at": row["created_at"]})
            if expected != row["content_hash"]:
                raise ValueError("hash de evento de identidade inválido")
            previous = str(row["content_hash"])
        return previous
