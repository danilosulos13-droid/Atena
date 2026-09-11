#!/usr/bin/env python3
"""Converte o relatório de aprendizagem em voz e envia via Telegram."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from core.audio_gateway import AudioGateway, AudioGatewayError
from core.learning_audio import build_learning_spoken_text


def send_voice(token: str, chat_id: str, audio_path: Path, timeout: int = 60) -> None:
    boundary = "----AtenaVoiceBoundary7MA4YWxkTrZu0gW"
    chunks: list[bytes] = []
    def field(name: str, value: str) -> None:
        chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), value.encode(), b"\r\n"])
    field("chat_id", chat_id)
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="voice"; filename="atena-learning.wav"\r\n',
        b"Content-Type: audio/wav\r\n\r\n",
        audio_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendVoice",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou o áudio: {body.get('description', 'erro desconhecido')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--synthesize-only", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        spoken = build_learning_spoken_text(payload)
        if args.dry_run:
            print(spoken)
            return 0
        if args.synthesize_only:
            with tempfile.TemporaryDirectory(prefix="atena-learning-audio-test-") as tmp:
                audio_path = AudioGateway().synthesize(spoken, Path(tmp) / "learning.wav")
                print(f"Síntese local concluída: {audio_path.stat().st_size} bytes")
            return 0
        token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            message = "Telegram não configurado para áudio de aprendizagem."
            if args.allow_missing:
                print(f"::warning::{message}")
                return 0
            raise RuntimeError(message)
        with tempfile.TemporaryDirectory(prefix="atena-learning-audio-") as tmp:
            audio_path = AudioGateway().synthesize(spoken, Path(tmp) / "learning.wav")
            send_voice(token, chat_id, audio_path)
        print("Áudio de aprendizagem enviado ao Telegram.")
        return 0
    except (OSError, json.JSONDecodeError, AudioGatewayError, RuntimeError) as exc:
        print(f"::error::Falha no áudio de aprendizagem: {type(exc).__name__}: {exc}")
        return 0 if args.allow_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
