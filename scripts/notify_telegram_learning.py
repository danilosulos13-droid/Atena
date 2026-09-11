#!/usr/bin/env python3
"""Envia um resumo seguro de uma nova aprendizagem via Telegram Bot API."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def clip(value: str, limit: int = 700) -> str:
    value = " ".join(value.replace("\n", " ").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _safe_url(value: object) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def _format_insight(item: object, index: int) -> tuple[str, list[str]]:
    if not isinstance(item, dict):
        return f"• {html.escape(clip(str(item)))}", []
    text = clip(str(item.get("text", "limitação sem descrição")), 900)
    kind = html.escape(str(item.get("type", "insight")))
    try:
        confidence = float(item.get("confidence", 0.0))
        confidence_text = f"{confidence:.2f}"
    except (TypeError, ValueError):
        confidence_text = "0.00"
    raw_refs = [str(ref).strip() for ref in item.get("evidence_refs", []) or [] if str(ref).strip()]
    refs = list(dict.fromkeys(raw_refs))
    lines = [
        f"<b>{index}. {html.escape(kind)}</b> · confiança: <code>{confidence_text}</code>",
        html.escape(text),
    ]
    for ref_index, ref in enumerate(refs[:5], 1):
        safe_url = _safe_url(ref)
        if safe_url:
            lines.append(f"<a href=\"{html.escape(safe_url, quote=True)}\">Fonte {ref_index}</a>")
        else:
            lines.append(f"Fonte {ref_index}: <code>{html.escape(ref)}</code>")
    return "\n".join(f"• {line}" if line == lines[0] else f"  {line}" for line in lines), refs


def build_message(proposal: dict, run_url: str | None) -> str:
    observations = proposal.get("observations", {})
    insights = observations.get("insights", [])
    risks = observations.get("risks", [])
    changes = observations.get("proposed_changes", [])
    next_cycle = observations.get("next_cycle", [])
    research_plan = observations.get("research_plan", {})
    research = proposal.get("research", {})
    model = html.escape(str(proposal.get("model", "modelo local")))
    provider = html.escape(str(proposal.get("provider", "desconhecido")))
    requested_by = research.get("requested_by", "rotation")
    timestamp = html.escape(str(proposal.get("timestamp", "agora")))
    lines = [
        "<b>ATENA — nova aprendizagem</b>",
        f"Provider: <code>{provider}</code>",
        f"Modelo: <code>{model}</code>",
        f"Ciclo: <code>{timestamp}</code>",
        "",
        "<b>Insights</b>",
    ]
    all_refs: list[str] = []
    for index, item in enumerate(insights[:5], 1):
        formatted, refs = _format_insight(item, index)
        lines.append(formatted)
        all_refs.extend(refs)
    all_refs = list(dict.fromkeys(all_refs))
    lines.append("\n<b>Riscos</b>")
    lines.extend(f"• {html.escape(clip(str(item)))}" for item in risks[:5])
    lines.append("\n<b>Propostas geradas</b>")
    for change in changes[:5]:
        if isinstance(change, dict):
            lines.append(f"• <code>{html.escape(clip(str(change.get('file', 'arquivo desconhecido')), 180))}</code>")
    lines.append("\n<b>Próximo ciclo</b>")
    lines.extend(f"• {html.escape(clip(str(item)))}" for item in next_cycle[:3])
    lines.append("\n<b>Pesquisa realizada</b>")
    lines.append(f"• Origem: {html.escape(str(requested_by))}")
    if research_plan.get("topic"):
        lines.append(f"• Tema: {html.escape(clip(str(research_plan['topic']), 180))}")
    consulted = research_plan.get("sources_to_consult", []) or [item.get("source") for item in research.get("sources", []) if item.get("ok")]
    rss_consulted = [item.get("source") for item in research.get("rss_sources", []) if item.get("ok")]
    consulted = list(dict.fromkeys([*consulted, *rss_consulted]))
    if consulted:
        lines.append(f"• Fontes consultadas: {html.escape(clip(', '.join(map(str, consulted)), 300))}")
    if all_refs:
        lines.append("\n<b>Referências dos insights</b>")
        for index, ref in enumerate(all_refs[:10], 1):
            lines.append(f"{index}. <a href=\"{html.escape(ref, quote=True)}\">{html.escape(clip(ref, 180))}</a>")
    if research_plan.get("question"):
        lines.append(f"• Pergunta: {html.escape(clip(str(research_plan['question']), 360))}")
    if research_plan.get("next_test"):
        lines.append(f"• Próximo teste: {html.escape(clip(str(research_plan['next_test']), 360))}")
    if run_url:
        lines.append(f"\n<a href=\"{html.escape(run_url, quote=True)}\">Ver execução no GitHub Actions</a>")
    message = "\n".join(lines)
    if len(message) <= 3900:
        return message

    # Nunca corte HTML no meio de uma tag ou entidade: o Telegram responde
    # HTTP 400 quando parse_mode=HTML recebe markup incompleto. Neste caso,
    # enviamos um resumo compacto, sem links, mas ainda formatado validamente.
    compact_parts = [
        "<b>ATENA — nova aprendizagem</b>",
        f"Provider: <code>{provider}</code>",
        f"Modelo: <code>{model}</code>",
        f"Ciclo: <code>{timestamp}</code>",
        "",
        "<b>Resumo dos insights</b>",
    ]
    for index, item in enumerate(insights[:3], 1):
        if isinstance(item, dict):
            text = clip(str(item.get("text", "limitação sem descrição")), 700)
        else:
            text = clip(str(item), 700)
        compact_parts.append(f"• {index}. {html.escape(text)}")
    compact = "\n".join(compact_parts)
    if len(compact) <= 3900:
        return compact
    prefix = "<b>ATENA — nova aprendizagem</b>\n"
    return prefix + html.escape(clip("Resumo: " + compact, 3900 - len(prefix)))


def build_speech(proposal: dict) -> str:
    """Gera texto curto e sem markup para o TTS."""
    observations = proposal.get("observations", {})
    insights = observations.get("insights", []) or []
    risks = observations.get("risks", []) or []
    changes = observations.get("proposed_changes", []) or []
    parts = ["Resumo da nova aprendizagem da Atena."]
    for index, item in enumerate(insights[:3], 1):
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        if text:
            parts.append(f"Insight {index}: {clip(str(text), 500)}.")
        if isinstance(item, dict):
            refs = [str(ref).strip() for ref in item.get("evidence_refs", []) or [] if str(ref).strip()]
            if refs:
                parts.append(f"Evidências do insight {index}: {', '.join(refs[:5])}.")
    if risks:
        parts.append(f"Foram identificados {len(risks[:5])} riscos.")
    if changes:
        files = [item.get("file") for item in changes[:3] if isinstance(item, dict) and item.get("file")]
        if files:
            parts.append("Propostas de mudança: " + ", ".join(map(str, files)) + ".")
    next_cycle = observations.get("next_cycle", []) or []
    if next_cycle:
        parts.append("Próximo ciclo: " + clip(str(next_cycle[0]), 400) + ".")
    return " ".join(" ".join(parts).split())[:3499]


def _telegram_request(endpoint: str, payload: dict[str, str], timeout: int) -> dict:
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(endpoint, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("description", raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem: {body.get('description', 'erro desconhecido')}")
    return body


def send(token: str, chat_id: str, message: str, timeout: int = 15) -> None:
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    try:
        _telegram_request(endpoint, payload, timeout)
    except RuntimeError as exc:
        # Mantém a notificação funcionando mesmo quando uma entidade HTML
        # inesperada for rejeitada pelo parser do Telegram.
        if "HTTP 400" not in str(exc):
            raise
        plain = re.sub(r"<[^>]+>", "", message)
        plain = html.unescape(plain)
        _telegram_request(endpoint, {"chat_id": chat_id, "text": plain, "disable_web_page_preview": "true"}, timeout)


def send_voice(token: str, chat_id: str, audio_path: Path, timeout: int = 60) -> None:
    """Envia WAV como mensagem de voz; não envia fallback textual."""
    import requests

    endpoint = f"https://api.telegram.org/bot{token}/sendVoice"
    with audio_path.open("rb") as audio:
        response = requests.post(
            endpoint,
            data={"chat_id": chat_id},
            files={"voice": ("atena-learning.wav", audio, "audio/wav")},
            timeout=timeout,
        )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou o áudio: {body.get('description', 'erro desconhecido')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--run-url", default=os.getenv("GITHUB_SERVER_URL", "") + "/" + os.getenv("GITHUB_REPOSITORY", "") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--voice", action="store_true", help="envia o resumo como áudio WAV via Telegram")
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
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        if args.voice:
            # O áudio é opcional; o import tardio mantém o envio textual
            # funcionando em runners sem o runtime de voz instalado.
            from core.audio_gateway import AudioGateway

            gateway = AudioGateway()
            audio_path = gateway.synthesize(build_speech(proposal))
            try:
                send_voice(token, chat_id, audio_path)
            finally:
                gateway.remove_file(audio_path)
        else:
            message = build_message(proposal, args.run_url or None)
            send(token, chat_id, message)
    except Exception as exc:
        print(f"::error::Falha ao enviar notificação Telegram: {type(exc).__name__}: {exc}")
        return 1
    print("Notificação Telegram enviada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
