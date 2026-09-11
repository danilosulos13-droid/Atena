"""Análise controlada de imagens recebidas pela Atena."""
from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests


class VisionAnalysisError(RuntimeError):
    pass


def _ocr(path: Path) -> str:
    try:
        result = subprocess.run(["tesseract", str(path), "stdout", "-l", os.getenv("ATENA_OCR_LANG", "por+eng")], capture_output=True, text=True, timeout=30, check=True)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise VisionAnalysisError("OCR indisponível") from exc
    return result.stdout.strip()[:12000]


def analyze_image(path: str | Path, prompt: str, *, model: str | None = None, max_bytes: int = 15 * 1024 * 1024) -> str:
    image = Path(path)
    if not image.is_file():
        raise VisionAnalysisError("imagem não encontrada")
    if image.stat().st_size > max_bytes:
        raise VisionAnalysisError("imagem excede o limite de 15 MB")
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    endpoint = os.getenv("ATENA_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
    vision_model = model or os.getenv("ATENA_VISION_MODEL", "qwen2.5vl:3b")
    payload = {
        "model": vision_model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt[:4000], "images": [encoded]}],
        "options": {"temperature": 0.1},
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=int(os.getenv("ATENA_VISION_TIMEOUT", "120")))
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        answer = str((body.get("message") or {}).get("content", "")).strip()
    except (requests.RequestException, ValueError) as exc:
        raise VisionAnalysisError(f"modelo de visão indisponível: {type(exc).__name__}") from exc
    if not answer:
        raise VisionAnalysisError("modelo de visão não retornou conteúdo")
    return answer[:12000]


def analyze_image_with_ocr_fallback(path: str | Path, prompt: str, *, model: str | None = None) -> str:
    try:
        return analyze_image(path, prompt, model=model)
    except VisionAnalysisError as vision_error:
        text = _ocr(Path(path))
        if text:
            return f"Análise visual indisponível ({vision_error}). Texto OCR extraído:\n\n{text}"
        raise
