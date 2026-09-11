"""Cliente assíncrono para despachar intenções ao gateway Tasker."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import aiohttp


class TaskerNotConfigured(RuntimeError):
    pass


class TaskerDispatchError(RuntimeError):
    pass


class TaskerClient:
    def __init__(self, base_url: str | None = None, secret: str | None = None, timeout: int = 20) -> None:
        self.base_url = (base_url or os.getenv("ATENA_TASKER_DISPATCH_URL", "")).rstrip("/")
        self.secret = (secret or os.getenv("ATENA_TASKER_HMAC_SECRET", "")).strip()
        self.device_id = os.getenv("ATENA_TASKER_DEVICE_ID", "android-principal").strip()
        self.timeout = timeout

    async def _post_signed(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url or len(self.secret) < 32:
            raise TaskerNotConfigured("configure ATENA_TASKER_DISPATCH_URL e ATENA_TASKER_HMAC_SECRET")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        message = f"{timestamp}.{nonce}.".encode("utf-8") + body
        signature = hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-Atena-Timestamp": timestamp, "X-Atena-Nonce": nonce, "X-Atena-Signature": signature}
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}{path}", data=body, headers=headers) as response:
                    data = await response.json(content_type=None)
                    if response.status != 200 or not data.get("accepted"):
                        raise TaskerDispatchError(str(data.get("detail", data)))
                    return data
        except aiohttp.ClientError as exc:
            raise TaskerDispatchError(f"gateway Tasker indisponível: {exc}") from exc

    async def approve(self, *, approval_id: str, requester_chat_id: str, action: str, target: str, parameters: dict[str, Any], expires_in: int = 120) -> dict[str, Any]:
        return await self._post_signed("/v1/tasker/approve", {"approval_id": approval_id, "requester_chat_id": str(requester_chat_id), "device_id": self.device_id, "action": action, "target": target, "parameters": parameters, "expires_in": expires_in})

    async def dispatch(self, *, action: str, target: str, parameters: dict[str, Any], command_id: str | None = None, approval_id: str | None = None) -> dict[str, Any]:
        if not self.base_url or len(self.secret) < 32:
            raise TaskerNotConfigured("configure ATENA_TASKER_DISPATCH_URL e ATENA_TASKER_HMAC_SECRET")
        command_id = command_id or f"task-{uuid.uuid4().hex[:18]}"
        payload = {"command_id": command_id, "approval_id": approval_id, "device_id": self.device_id, "action": action, "target": target, "parameters": parameters}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        message = f"{timestamp}.{nonce}.".encode("utf-8") + body
        signature = hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-Atena-Timestamp": timestamp, "X-Atena-Nonce": nonce, "X-Atena-Signature": signature}
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}/v1/tasker/dispatch", data=body, headers=headers) as response:
                    data = await response.json(content_type=None)
                    if response.status != 200 or not data.get("accepted"):
                        raise TaskerDispatchError(str(data.get("detail", data)))
                    return data
        except aiohttp.ClientError as exc:
            raise TaskerDispatchError(f"gateway Tasker indisponível: {exc}") from exc
