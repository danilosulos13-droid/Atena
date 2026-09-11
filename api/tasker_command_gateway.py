"""Gateway HTTP para comandos autorizados do Tasker.

Assinatura:
  HMAC-SHA256(secret, f"{timestamp}.{nonce}." + body_bytes)

Headers:
  X-Atena-Timestamp: Unix timestamp em segundos
  X-Atena-Nonce: identificador único da requisição
  X-Atena-Signature: hex digest HMAC-SHA256

O gateway não executa comandos Android arbitrários. Ele somente aceita a
whitelist e devolve uma intenção estruturada para o chamador encaminhar à
Atena/Telegram.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.google_sheets_audit import GoogleSheetsAudit, GoogleSheetsNotConfigured

ALLOWED_COMMANDS = {
    "consultar bateria",
    "abrir spotify",
    "pausar mídia",
    "agenda",
    "status atena",
}
MAX_SKEW_SECONDS = int(os.getenv("ATENA_TASKER_MAX_SKEW_SECONDS", "90"))
NONCE_TTL_SECONDS = int(os.getenv("ATENA_TASKER_NONCE_TTL_SECONDS", "300"))
DB_PATH = Path(os.getenv("ATENA_TASKER_GATEWAY_DB", "atena_evolution/tasker_gateway.sqlite3"))

app = FastAPI(title="Atena Tasker Command Gateway", version="1.0")


class TaskerCommand(BaseModel):
    command: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    timestamp: int | None = None
    nonce: str | None = Field(default=None, min_length=8, max_length=160)


class TaskerDispatch(BaseModel):
    command_id: str = Field(min_length=8, max_length=120)
    approval_id: str | None = Field(default=None, min_length=8, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskerResult(BaseModel):
    command_id: str = Field(min_length=8, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)


ALLOWED_TASK_ACTIONS = {
    "android_open_app",
    "android_media_play",
    "android_media_pause",
    "android_media_next",
    "android_media_previous",
    "spotify_search_open",
    "android_status",
    "android_call_contact",
    "android_send_message",
}
SENSITIVE_TASK_ACTIONS = {"android_call_contact", "android_send_message", "android_sensitive_action"}
APPROVAL_TTL_SECONDS = int(os.getenv("ATENA_TASKER_APPROVAL_TTL_SECONDS", "120"))


def _secret() -> bytes:
    value = os.getenv("ATENA_TASKER_HMAC_SECRET", "")
    if len(value) < 32:
        raise HTTPException(status_code=503, detail="gateway HMAC não configurado")
    return value.encode("utf-8")


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS used_nonces (nonce TEXT PRIMARY KEY, used_at INTEGER NOT NULL)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS task_approvals (
            approval_id TEXT PRIMARY KEY,
            requester_chat_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            action TEXT NOT NULL,
            intent_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            consumed_at INTEGER
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS task_queue (
            command_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            claimed_at INTEGER,
            completed_at INTEGER,
            result_json TEXT
        )"""
    )
    connection.commit()
    return connection


def _clean_nonces(connection: sqlite3.Connection, now: int) -> None:
    connection.execute("DELETE FROM used_nonces WHERE used_at < ?", (now - NONCE_TTL_SECONDS,))


def _verify_signature(raw_body: bytes, timestamp: str, nonce: str, signature: str) -> None:
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="timestamp inválido") from exc
    if abs(int(time.time()) - timestamp_int) > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="timestamp expirado")
    if not nonce or len(nonce) < 8:
        raise HTTPException(status_code=401, detail="nonce ausente ou curto")
    signed = f"{timestamp}.{nonce}.".encode("utf-8") + raw_body
    expected = hmac.new(_secret(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(status_code=401, detail="assinatura inválida")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "atena-tasker-gateway"}


def _audit_command(command: str, device_id: str, accepted: bool, details: str = "") -> None:
    if os.getenv("ATENA_AUDIT_SHEETS_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        return
    try:
        GoogleSheetsAudit().append_command(
            command=command,
            device_id=device_id,
            accepted=accepted,
            source="tasker",
            details=details,
        )
    except (GoogleSheetsNotConfigured, Exception):
        # Auditoria nunca deve fazer o comando autorizado falhar; registrar em log
        # em produção para reprocessamento posterior.
        return


@app.post("/v1/tasker/commands")
async def receive_tasker_command(
    request: Request,
    background_tasks: BackgroundTasks,
    x_atena_timestamp: str | None = Header(default=None),
    x_atena_nonce: str | None = Header(default=None),
    x_atena_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    raw_body = await request.body()
    _verify_signature(raw_body, x_atena_timestamp or "", x_atena_nonce or "", x_atena_signature or "")
    try:
        payload = TaskerCommand.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payload JSON inválido") from exc
    command = " ".join(payload.command.lower().split())
    if command not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail="comando não autorizado")
    now = int(time.time())
    connection = _db()
    try:
        _clean_nonces(connection, now)
        try:
            connection.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?, ?)", (x_atena_nonce, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="nonce já utilizado") from exc
        connection.commit()
    finally:
        connection.close()
    background_tasks.add_task(_audit_command, command, payload.device_id, True)
    return {
        "accepted": True,
        "intent": "device_command",
        "command": command,
        "device_id": payload.device_id,
        "source": "tasker",
        "received_at": now,
    }


def sign_tasker_payload(payload: dict[str, Any], secret: str, timestamp: int, nonce: str) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    message = f"{timestamp}.{nonce}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


@app.post("/v1/tasker/dispatch")
async def dispatch_tasker_intent(
    request: Request,
    background_tasks: BackgroundTasks,
    x_atena_timestamp: str | None = Header(default=None),
    x_atena_nonce: str | None = Header(default=None),
    x_atena_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Enfileira uma intenção já classificada pela Atena para o Tasker."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_atena_timestamp or "", x_atena_nonce or "", x_atena_signature or "")
    try:
        payload = TaskerDispatch.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payload de intenção inválido") from exc
    if payload.action not in ALLOWED_TASK_ACTIONS:
        raise HTTPException(status_code=403, detail="ação Android fora da allowlist")
    now = int(time.time())
    intent_hash = _intent_hash(payload.action, payload.target, payload.parameters, payload.device_id)
    if payload.action in SENSITIVE_TASK_ACTIONS:
        if not payload.approval_id:
            raise HTTPException(status_code=428, detail="aprovação explícita obrigatória")
        approval = _consume_approval(payload.approval_id, payload.device_id, payload.action, intent_hash, now)
        if approval is None:
            raise HTTPException(status_code=403, detail="aprovação ausente, expirada ou incompatível")
    connection = _db()
    try:
        _clean_nonces(connection, now)
        try:
            connection.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?, ?)", (x_atena_nonce, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="nonce já utilizado") from exc
        connection.execute(
            """INSERT OR IGNORE INTO task_queue
            (command_id, device_id, action, target, parameters_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (payload.command_id, payload.device_id, payload.action, payload.target, json.dumps(payload.parameters, ensure_ascii=False), now),
        )
        connection.commit()
    finally:
        connection.close()
    background_tasks.add_task(_audit_command, payload.action, payload.device_id, True, json.dumps(payload.parameters, ensure_ascii=False))
    return {"accepted": True, "command_id": payload.command_id, "status": "queued", "device_id": payload.device_id}


@app.post("/v1/tasker/next")
async def claim_next_task(
    request: Request,
    x_atena_timestamp: str | None = Header(default=None),
    x_atena_nonce: str | None = Header(default=None),
    x_atena_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Retira uma única tarefa pendente para o dispositivo autenticado."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_atena_timestamp or "", x_atena_nonce or "", x_atena_signature or "")
    try:
        payload = json.loads(raw_body or b"{}")
        device_id = str(payload.get("device_id", "")).strip()
    except (json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="payload JSON inválido") from exc
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id obrigatório")
    now = int(time.time())
    connection = _db()
    try:
        _clean_nonces(connection, now)
        try:
            connection.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?, ?)", (x_atena_nonce, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="nonce já utilizado") from exc
        row = connection.execute(
            "SELECT command_id, action, target, parameters_json FROM task_queue WHERE device_id=? AND status='queued' ORDER BY created_at LIMIT 1",
            (device_id,),
        ).fetchone()
        if row is None:
            connection.commit()
            return {"task": None, "device_id": device_id}
        connection.execute("UPDATE task_queue SET status='claimed', claimed_at=? WHERE command_id=?", (now, row[0]))
        connection.commit()
        return {"task": {"command_id": row[0], "action": row[1], "target": row[2], "parameters": json.loads(row[3])}, "device_id": device_id}
    finally:
        connection.close()


@app.post("/v1/tasker/result")
async def complete_task(
    request: Request,
    background_tasks: BackgroundTasks,
    x_atena_timestamp: str | None = Header(default=None),
    x_atena_nonce: str | None = Header(default=None),
    x_atena_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    raw_body = await request.body()
    _verify_signature(raw_body, x_atena_timestamp or "", x_atena_nonce or "", x_atena_signature or "")
    try:
        payload = TaskerResult.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="resultado inválido") from exc
    now = int(time.time())
    connection = _db()
    try:
        _clean_nonces(connection, now)
        try:
            connection.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?, ?)", (x_atena_nonce, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="nonce já utilizado") from exc
        status = "completed" if payload.ok else "failed"
        updated = connection.execute(
            "UPDATE task_queue SET status=?, completed_at=?, result_json=? WHERE command_id=? AND device_id=?",
            (status, now, json.dumps(payload.result, ensure_ascii=False), payload.command_id, payload.device_id),
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    if not updated:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    background_tasks.add_task(_audit_command, payload.command_id, payload.device_id, payload.ok, json.dumps(payload.result, ensure_ascii=False))
    return {"accepted": True, "command_id": payload.command_id, "status": status}


class TaskerApproval(BaseModel):
    approval_id: str = Field(min_length=8, max_length=120)
    requester_chat_id: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expires_in: int = Field(default=120, ge=30, le=300)


def _intent_hash(action: str, target: str, parameters: dict[str, Any], device_id: str) -> str:
    canonical = json.dumps(
        {"action": action, "device_id": device_id, "parameters": parameters, "target": target},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _consume_approval(approval_id: str, device_id: str, action: str, intent_hash: str, now: int) -> bool:
    connection = _db()
    try:
        row = connection.execute(
            "SELECT status, device_id, action, intent_hash, expires_at FROM task_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        if not row or row[0] != "approved" or row[1] != device_id or row[2] != action or row[3] != intent_hash or int(row[4]) < now:
            return False
        updated = connection.execute(
            "UPDATE task_approvals SET status='consumed', consumed_at=? WHERE approval_id=? AND status='approved'",
            (now, approval_id),
        ).rowcount
        connection.commit()
        return bool(updated)
    finally:
        connection.close()


@app.post("/v1/tasker/approve")
async def approve_tasker_intent(
    request: Request,
    background_tasks: BackgroundTasks,
    x_atena_timestamp: str | None = Header(default=None),
    x_atena_nonce: str | None = Header(default=None),
    x_atena_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Registra uma aprovação emitida após confirmação explícita no Telegram."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_atena_timestamp or "", x_atena_nonce or "", x_atena_signature or "")
    try:
        payload = TaskerApproval.model_validate_json(raw_body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="aprovação inválida") from exc
    if payload.action not in SENSITIVE_TASK_ACTIONS or payload.action not in ALLOWED_TASK_ACTIONS:
        raise HTTPException(status_code=403, detail="ação não pode ser aprovada")
    now = int(time.time())
    expires_at = now + min(payload.expires_in, APPROVAL_TTL_SECONDS)
    connection = _db()
    try:
        _clean_nonces(connection, now)
        try:
            connection.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?, ?)", (x_atena_nonce, now))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="nonce já utilizado") from exc
        connection.execute(
            """INSERT OR REPLACE INTO task_approvals
            (approval_id, requester_chat_id, device_id, action, intent_hash, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, 'approved', ?, ?)""",
            (payload.approval_id, payload.requester_chat_id, payload.device_id, payload.action, _intent_hash(payload.action, payload.target, payload.parameters, payload.device_id), now, expires_at),
        )
        connection.commit()
    finally:
        connection.close()
    background_tasks.add_task(_audit_command, payload.action, payload.device_id, True, f"approval_id={payload.approval_id}; expires_at={expires_at}")
    return {"accepted": True, "approval_id": payload.approval_id, "status": "approved", "expires_at": expires_at}
