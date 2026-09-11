"""Webhook Telegram para Vercel Functions.

A função é deliberadamente stateless: recebe um update do Telegram, valida o
secret token e o chat permitido, encaminha o evento a um backend público da
Atena e devolve ao Telegram a resposta produzida pelo backend.

Variáveis obrigatórias na Vercel:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_WEBHOOK_SECRET
    TELEGRAM_ALLOWED_CHAT_IDS
    ATENA_BACKEND_URL

Variável opcional:
    ATENA_BACKEND_SECRET

O backend deve aceitar POST em ATENA_BACKEND_URL e devolver JSON como:
    {"text": "resposta da Atena"}

Opcionalmente, pode devolver:
    {"text": "...", "voice_url": "https://.../audio.ogg"}
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib import error, request

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("atena.telegram.webhook")
app = FastAPI(title="Atena Telegram Webhook", version="1.0.0")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"configuração ausente: {name}")
    return value


def _allowed_chat_ids() -> set[str]:
    return {
        value.strip()
        for value in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if value.strip()
    }


def _telegram_api(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _required("TELEGRAM_BOT_TOKEN")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Telegram indisponível: {type(exc).__name__}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram recusou {method}")
    return result


def _dispatch_to_atena(update: dict[str, Any], chat_id: str) -> dict[str, Any]:
    backend_url = _required("ATENA_BACKEND_URL")
    headers = {"Content-Type": "application/json"}
    backend_secret = os.getenv("ATENA_BACKEND_SECRET", "").strip()
    if backend_secret:
        headers["X-Atena-Webhook-Secret"] = backend_secret
    body = json.dumps({"source": "telegram", "chat_id": chat_id, "update": update}, ensure_ascii=False).encode("utf-8")
    req = request.Request(backend_url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"backend da Atena indisponível: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("backend da Atena devolveu resposta inválida")
    return payload


def _chat_and_message(update: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("id") is None:
        return None
    return str(chat["id"]), message


@app.get("/api/telegram/webhook")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "atena-telegram-webhook"}


@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request_obj: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    expected_secret = _required("TELEGRAM_WEBHOOK_SECRET")
    if x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="invalid webhook secret")

    try:
        update = await request_obj.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="invalid update")

    extracted = _chat_and_message(update)
    if extracted is None:
        # Acknowledge non-message updates so Telegram does not retry them.
        return JSONResponse({"ok": True, "ignored": "unsupported_update"})
    chat_id, _message = extracted
    allowed = _allowed_chat_ids()
    if not allowed or chat_id not in allowed:
        raise HTTPException(status_code=403, detail="chat not allowed")

    try:
        result = _dispatch_to_atena(update, chat_id)
        text = result.get("text")
        voice_url = result.get("voice_url")
        if isinstance(text, str) and text.strip():
            _telegram_api("sendMessage", {"chat_id": chat_id, "text": text[:4096]})
        if isinstance(voice_url, str) and voice_url.startswith(("https://", "http://")):
            _telegram_api("sendVoice", {"chat_id": chat_id, "voice": voice_url})
    except RuntimeError as exc:
        # Keep sensitive payloads out of logs. Telegram will retry the update.
        log.error("falha controlada no processamento do update: %s", exc)
        raise HTTPException(status_code=503, detail="processing unavailable") from exc

    return JSONResponse({"ok": True})
