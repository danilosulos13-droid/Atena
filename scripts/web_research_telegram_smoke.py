from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime, timezone

import requests

from core.web_research import search_web


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste manual da pesquisa web via Telegram")
    parser.add_argument("--question", required=True)
    args = parser.parse_args()
    token = os.environ["ATENA_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["ATENA_TELEGRAM_CHAT_ID"]
    evidence = search_web(args.question, limit=5)
    if not evidence:
        raise SystemExit("Pesquisa abortada: nenhuma fonte web confirmada foi encontrada.")

    lines = [
        "<b>ATENA — simulação de pesquisa web</b>",
        f"Consulta: <i>{html.escape(args.question)}</i>",
        f"Realizada em: <code>{datetime.now(timezone.utc).isoformat()}</code>",
        "",
        "A busca web encontrou estas fontes públicas:",
    ]
    for index, item in enumerate(evidence, 1):
        lines.extend([
            f"<b>{index}. {html.escape(item.title)}</b>",
            html.escape(item.snippet[:420]) if item.snippet else "Trecho não disponível.",
            f'<a href="{html.escape(item.url, quote=True)}">Abrir fonte</a>',
            "",
        ])
    message = "\n".join(lines)
    if len(message) > 3900:
        message = message[:3890] + "..."
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram rejeitou a simulação: {data.get('description', 'erro desconhecido')}")
    print(f"Simulação enviada com {len(evidence)} fontes confirmadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
