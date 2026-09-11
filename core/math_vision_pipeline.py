"""Pipeline imagem matemática -> transcrição -> solução -> memória vetorial."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import requests

from core.vision_analysis import VisionAnalysisError


class MathVisionError(RuntimeError):
    pass


def _ask_vision(path: Path, prompt: str, model: str) -> dict[str, Any]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "stream": False,
        "format": {
            "type": "object",
            "properties": {
                "transcription": {"type": "string"},
                "interpretation": {"type": "string"},
                "solution": {"type": "string"},
                "numeric_answer": {"type": "string"},
                "first_digits": {"type": "string"},
                "confidence": {"type": "number"},
                "checks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["transcription", "interpretation", "solution", "numeric_answer", "first_digits", "confidence", "checks"],
        },
        "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
    }
    try:
        response = requests.post(os.getenv("ATENA_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat"), json=payload, timeout=int(os.getenv("ATENA_VISION_TIMEOUT", "180")))
        response.raise_for_status()
        content = str((response.json().get("message") or {}).get("content", ""))
        result = json.loads(content)
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        raise MathVisionError(f"não foi possível obter solução estruturada: {type(exc).__name__}") from exc
    if not isinstance(result, dict) or not result.get("transcription") or not result.get("numeric_answer"):
        raise MathVisionError("a visão não retornou uma expressão matemática completa")
    return result


def solve_math_image(path: str | Path, *, memory: Any | None = None) -> dict[str, Any]:
    image = Path(path)
    if not image.is_file():
        raise MathVisionError("imagem não encontrada")
    prompt = (
        "Resolva o desafio matemático visível na imagem com rigor. Primeiro transcreva exatamente a expressão; "
        "depois explique a interpretação dos limites, séries e integrais; faça a solução passo a passo; calcule o "
        "valor numérico com precisão; informe os primeiros dígitos sem remover zeros à esquerda; e liste verificações. "
        "Se algum símbolo estiver ilegível, marque a incerteza em vez de inventar. Responda somente no JSON solicitado."
    )
    result = _ask_vision(image, prompt, os.getenv("ATENA_VISION_MODEL", "gemma4"))
    result["source"] = "telegram_image"
    result["memory_hits"] = []
    try:
        from core.autonomous_learning import Experience, ExperienceLedger
        ExperienceLedger().append(
            Experience(
                prompt=f"Resolva a expressão matemática: {result['transcription']}",
                response=(
                    f"Interpretação: {result['interpretation']}\n"
                    f"Solução: {result['solution']}\n"
                    f"Valor numérico: {result['numeric_answer']}\n"
                    f"Primeiros dígitos: {result['first_digits']}\n"
                    f"Verificações: {'; '.join(str(item) for item in result.get('checks', []))}"
                ),
                score=max(0.65, min(1.0, float(result.get("confidence", 0.8)))),
                source="telegram_math_vision",
                topic="matemática por imagem",
            )
        )
    except Exception:
        # A resposta não deve falhar apenas porque a persistência de aprendizagem
        # está indisponível; a memória vetorial continua sendo tentada abaixo.
        result["learning_warning"] = "experiência não persistida no ledger"
    if memory is not None:
        try:
            query = result["transcription"]
            result["memory_hits"] = memory.recall(query, top_k=3)
            memory.remember(
                f"Problema: {result['transcription']}\nInterpretação: {result['interpretation']}\nSolução: {result['solution']}\nValor: {result['numeric_answer']}\nPrimeiros dígitos: {result['first_digits']}",
                metadata={"kind": "math_resolution", "numeric_answer": result["numeric_answer"], "transcription": result["transcription"]},
                tags=["math", "vision", "verified_candidate"],
                importance=0.9,
            )
        except Exception as exc:
            result["memory_warning"] = f"memória vetorial indisponível: {type(exc).__name__}"
    return result


def format_math_solution(result: dict[str, Any]) -> str:
    lines = [
        "ATENA — resolução matemática por imagem",
        "",
        f"Transcrição: {result.get('transcription', '')}",
        f"Interpretação: {result.get('interpretation', '')}",
        "",
        f"Solução:\n{result.get('solution', '')}",
        "",
        f"Valor numérico: {result.get('numeric_answer', '')}",
        f"Primeiros dígitos: {result.get('first_digits', '')}",
        "",
        "Verificações:",
    ]
    lines.extend(f"• {item}" for item in result.get("checks", []))
    if result.get("memory_hits"):
        lines.append(f"\nEncontrei {len(result['memory_hits'])} resolução(ões) semelhante(s) na memória vetorial.")
    if result.get("memory_warning"):
        lines.append(f"\nAviso: {result['memory_warning']}")
    return "\n".join(lines)
