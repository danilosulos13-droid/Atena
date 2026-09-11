#!/usr/bin/env python3
"""Executa casos do benchmark com JSON estruturado e checkpoint resiliente.

O runner é deliberadamente serial por padrão para evitar OOM. Cada resposta é
persistida imediatamente; a execução pode ser interrompida e retomada sem
repetir casos concluídos.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.structured_benchmark import StructuredAnswer, response_schema

TRANSIENT_MARKERS = ("unexpected eof", "timeout", "timed out", "connection reset", "temporarily", "503", "502", "500")


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("status") == "ok":
            completed[str(item["task_id"])] = item
    return completed


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def build_prompt(case: dict[str, Any]) -> str:
    return f"""Você é Atena, um agente de análise verificável.
Responda SOMENTE com JSON compatível com o schema fornecido pelo campo format.
Não execute ferramentas: este benchmark não fornece ferramentas reais.
Não invente fontes, fatos ou resultados. Diferencie fatos, hipóteses, evidências,
incertezas, confiança e próximo teste. Para ações sensíveis, descreva apenas
política segura e confirmação; não execute a ação.

FAMÍLIA: {case.get('family')}
DOMÍNIO: {case.get('domain')}
TAREFA: {case.get('scenario')}
CAPACIDADES EXIGIDAS: {', '.join(case.get('required', []))}
RESTRIÇÕES: {', '.join(case.get('forbidden', []))}
"""


def classify_error(exc: Exception) -> str:
    text = str(exc).casefold()
    return "transient_infrastructure" if any(marker in text for marker in TRANSIENT_MARKERS) else "permanent_infrastructure"


def call_ollama(url: str, model: str, case: dict[str, Any], timeout: float, num_predict: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": build_prompt(case),
        "stream": False,
        "format": response_schema(),
        "keep_alive": 0,
        "options": {"temperature": 0.1, "num_predict": num_predict},
    }
    request = Request(
        url.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    text = raw.get("response")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("ollama_invalid_response")
    parsed = json.loads(text)
    answer = StructuredAnswer.model_validate(parsed)
    return {
        "raw_response": text,
        "answer": answer.model_dump(mode="json"),
        "tool_audit": {"executed": False, "calls": [], "reason": "Ollama /api/generate recebeu nenhuma ferramenta."},
    }


def execute_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    last_error: Exception | None = None
    attempts = max(1, args.retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            result = call_ollama(args.url, args.model, case, args.timeout, args.num_predict)
            return {
                "task_id": case["task_id"],
                "status": "ok",
                "model": args.model,
                "attempts": attempt,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                **result,
            }
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            error_class = classify_error(exc)
            if error_class != "transient_infrastructure" or attempt == attempts:
                return {
                    "task_id": case["task_id"],
                    "status": "infrastructure_error",
                    "error_class": error_class,
                    "error": str(exc),
                    "model": args.model,
                    "attempts": attempt,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            delay = args.backoff * (2 ** (attempt - 1)) + random.uniform(0, args.jitter)
            time.sleep(delay)
    raise AssertionError(last_error)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen2.5:3b-instruct")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff", type=float, default=5.0)
    parser.add_argument("--jitter", type=float, default=1.0)
    parser.add_argument("--num-predict", type=int, default=450)
    parser.add_argument("--sleep-between", type=float, default=2.0)
    parser.add_argument("--retry-errors", action="store_true", help="reprocessar task_ids que tinham erro no checkpoint")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    completed = load_completed(args.output)
    existing_ids = {item["task_id"] for item in completed.values()}
    errors_to_skip: set[str] = set()
    if args.output.exists() and not args.retry_errors:
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("status") != "ok":
                    errors_to_skip.add(str(item["task_id"]))

    counts = {"ok": 0, "skipped": 0, "infrastructure_error": 0}
    for case in cases:
        task_id = str(case["task_id"])
        if task_id in existing_ids or (task_id in errors_to_skip and not args.retry_errors):
            counts["skipped"] += 1
            continue
        result = execute_case(case, args)
        append_jsonl(args.output, result)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        time.sleep(max(0.0, args.sleep_between))

    print(json.dumps({"model": args.model, "total": len(cases), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
