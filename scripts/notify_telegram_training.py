#!/usr/bin/env python3
"""Envia o resumo de um ciclo de treino LoRA ao Telegram.

O script nunca imprime tokens. Com ``--allow-missing``, a ausência de secrets
apenas gera um warning, permitindo que o treino continue produzindo artefatos.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def clip(value: object, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _telegram_request(token: str, chat_id: str, message: str, timeout: int = 20) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail[:300]}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem: {body.get('description', 'erro desconhecido')}")


def build_message(payload: dict, run_url: str | None) -> str:
    training = payload.get("training") or {}
    collection = payload.get("collection") or {}
    performance = payload.get("performance_evaluation") or {}
    result = training.get("training") or training
    evaluation = training.get("evaluation") or {}
    status = str(result.get("status") or payload.get("training_status") or "failed").strip().lower()
    status_labels = {
        "candidate": "concluído — candidato salvo",
        "success": "concluído",
        "running": "em execução",
        "queued": "na fila",
        "failed": "falhou",
        "failure": "falhou",
        "cancelled": "cancelado",
        "skipped": "ignorado",
    }
    status_text = status_labels.get(status, f"estado: {status}")
    model = html.escape(str(payload.get("model") or result.get("base_model") or "não definido"))
    lines = [
        "<b>ATENA — resultado do ciclo LoRA</b>",
        f"Modelo-base: <code>{model}</code>",
        f"Status do treino: <code>{html.escape(status_text)}</code>",
    ]
    datasets = collection.get("datasets") or {}
    if datasets:
        lines.append(
            "Dataset: "
            f"<code>{datasets.get('sft', 0)} SFT</code>, "
            f"<code>{datasets.get('preferences', 0)} preferências</code>"
        )
    if result.get("examples") is not None:
        lines.append(f"Exemplos usados: <code>{result['examples']}</code>")
    if result.get("reason"):
        lines.append(f"Motivo: {html.escape(clip(result['reason'], 900))}")
    if evaluation:
        decision = evaluation.get("decision", "desconhecido")
        lines.append(f"Avaliação: <code>{html.escape(str(decision))}</code>")
        if evaluation.get("improvement") is not None:
            try:
                improvement = float(evaluation["improvement"]) * 100
                lines.append(f"Melhoria no holdout: <code>{improvement:.2f}%</code>")
            except (TypeError, ValueError):
                pass
        if evaluation.get("reason"):
            lines.append(f"Decisão: {html.escape(clip(evaluation['reason'], 900))}")
    if performance:
        lines.append(f"Desempenho automático: <code>{html.escape(str(performance.get('status', 'desconhecido')))}</code>")
        if performance.get("holdout_examples") is not None:
            lines.append(f"Holdout: <code>{performance['holdout_examples']} exemplos</code>")
        if performance.get("improvement") is not None:
            try:
                lines.append(f"Melhoria medida: <code>{float(performance['improvement']) * 100:.2f}%</code>")
            except (TypeError, ValueError):
                pass
        if performance.get("baseline", {}).get("perplexity") is not None and performance.get("candidate", {}).get("perplexity") is not None:
            lines.append(
                "Perplexidade: "
                f"<code>{float(performance['baseline']['perplexity']):.3f}</code> → "
                f"<code>{float(performance['candidate']['perplexity']):.3f}</code>"
            )
        if performance.get("reason"):
            lines.append(f"Avaliação: {html.escape(clip(performance['reason'], 700))}")
    if result.get("path"):
        lines.append(f"Candidato: <code>{html.escape(clip(result['path'], 300))}</code>")
    if run_url:
        lines.append(f'<a href="{html.escape(run_url, quote=True)}">Ver execução no GitHub Actions</a>')
    links = payload.get("research_links") or []
    if links:
        lines.append("<b>Fontes pesquisadas nesta execução:</b>")
        for item in links[:12]:
            if isinstance(item, str):
                url, title = item, item
            else:
                url = str(item.get("url") or "").strip()
                title = clip(item.get("title") or item.get("topic") or url, 120)
            if url.startswith(("https://", "http://")):
                lines.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(title)}</a>')
    else:
        lines.append("Fontes pesquisadas nesta execução: nenhuma fonte HTTP persistida.")
    return "\n".join(lines)[:3900]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--run-url", default=os.getenv("GITHUB_SERVER_URL", "") + "/" + os.getenv("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        message = "Telegram não configurado: defina ATENA_TELEGRAM_BOT_TOKEN e ATENA_TELEGRAM_CHAT_ID."
        if args.allow_missing:
            print(f"::warning::{message}")
            return 0
        print(f"::error::{message}")
        return 2

    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        _telegram_request(token, chat_id, build_message(payload, args.run_url or None))
    except Exception as exc:
        print(f"::error::Falha ao enviar resultado LoRA ao Telegram: {type(exc).__name__}: {exc}")
        return 1
    print("Resultado LoRA enviado ao Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
