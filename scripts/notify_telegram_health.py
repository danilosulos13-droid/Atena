#!/usr/bin/env python3
"""Envia alerta compacto de falha do sandbox rootless ao Telegram."""
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

from scripts.notify_telegram_learning import send


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        message = "Telegram não configurado para alerta do sandbox rootless."
        if args.allow_missing:
            print(f"::warning::{message}")
            return 0
        raise SystemExit(message)

    report = args.report.read_text(encoding="utf-8", errors="replace") if args.report.exists() else "relatório ausente"
    report = " ".join(report.split())
    report = report[:1800] + ("…" if len(report) > 1800 else "")
    message = (
        "<b>ATENA — falha no sandbox rootless</b>\n"
        "O ciclo foi bloqueado antes da execução.\n\n"
        f"<code>{html.escape(report)}</code>"
    )
    send(token, chat_id, message)
    print("Alerta de falha do sandbox enviado ao Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
