#!/usr/bin/env python3
"""Diagnostica o destino Telegram configurado sem imprimir token ou IDs sensíveis."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def api(token: str, method: str, payload: dict[str, str] | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} recusou a chamada: {body.get('description', 'erro desconhecido')}")
    return body


def main() -> int:
    token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("telegram_config=missing")
        return 2
    me = api(token, "getMe")["result"]
    target = api(token, "getChat", {"chat_id": chat_id})["result"]
    bot_id = str(me.get("id", ""))
    target_id = str(target.get("id", ""))
    print(json.dumps({
        "telegram_config": "loaded",
        "bot_username": me.get("username", ""),
        "target_type": target.get("type", ""),
        "target_username": target.get("username", ""),
        "target_title_present": bool(target.get("title")),
        "target_is_bot_itself": bool(bot_id and bot_id == target_id),
    }, ensure_ascii=False))
    if bot_id and bot_id == target_id:
        print("diagnosis=CHAT_ID points to the bot itself; use the human/group/channel chat ID")
        return 1
    print("diagnosis=target is not the bot itself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
