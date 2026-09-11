#!/usr/bin/env python3
"""Constrói um dataset de destilação auditável para QLoRA.

Entradas aceitas:
- training/sft.jsonl com ``messages``;
- training/experiences.jsonl com prompt/response/evidence;
- learning_memory.jsonl com payload/full_text/summary e source_url.

O script não inventa respostas. Dados externos precisam de URL HTTP(S); dados
curados podem usar ``curated://`` e permanecem identificados como curados.
A divisão é determinística por hash para que execuções repetidas não vazem
exemplos entre treino, validação e holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = [
    ROOT / "atena_evolution" / "training" / "sft.jsonl",
    ROOT / "atena_evolution" / "training" / "experiences.jsonl",
    ROOT / "atena_evolution" / "learning_memory.jsonl",
]


def clean(value: Any, limit: int = 24000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def valid_source(value: Any) -> bool:
    text = clean(value, 2000)
    if text.startswith("curated://"):
        return True
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def first_source(item: dict[str, Any], payload: dict[str, Any]) -> str:
    for key in ("source_url", "url", "source", "source_urls", "evidence", "evidence_refs"):
        value = item.get(key, payload.get(key))
        if isinstance(value, list):
            value = value[0] if value else ""
        if valid_source(value):
            return clean(value, 2000)
    return ""


def messages_from_item(item: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    messages = item.get("messages") or payload.get("messages")
    if isinstance(messages, list) and messages:
        normalized = []
        for message in messages:
            if isinstance(message, dict) and message.get("role") and message.get("content"):
                normalized.append({"role": clean(message["role"], 32), "content": clean(message["content"])})
        if len(normalized) >= 2:
            return normalized
    prompt = clean(item.get("prompt") or payload.get("prompt"))
    response = clean(
        item.get("response")
        or payload.get("response")
        or payload.get("full_text")
        or payload.get("summary")
        or item.get("answer")
        or payload.get("answer")
    )
    if not prompt or not response:
        return []
    return [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            value["_line"] = line_number
            yield value


def normalize(item: dict[str, Any], path: Path) -> dict[str, Any] | None:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
    messages = messages_from_item(item, payload)
    source_url = first_source(item, payload)
    if len(messages) < 2 or not source_url:
        return None
    user = messages[0]["content"]
    assistant = messages[-1]["content"]
    if len(user) < 12 or len(assistant) < 80:
        return None
    topic = clean(item.get("topic") or payload.get("topic") or "general", 160)
    domain = clean(item.get("domain") or payload.get("domain") or topic, 160)
    try:
        origin_file = str(path.relative_to(ROOT))
    except ValueError:
        origin_file = str(path)
    record = {
        "messages": messages,
        "source_url": source_url,
        "source_type": "curated" if source_url.startswith("curated://") else "web",
        "topic": topic,
        "domain": domain,
        "date": clean(item.get("published_at") or payload.get("published_at") or payload.get("date"), 64),
        "jurisdiction": clean(item.get("jurisdiction") or payload.get("jurisdiction"), 120),
        "origin_file": origin_file,
    }
    canonical = json.dumps(record["messages"], ensure_ascii=False, sort_keys=True)
    record["example_id"] = hashlib.sha256((canonical + "\n" + source_url).encode()).hexdigest()[:24]
    return record


def split_name(example_id: str) -> str:
    bucket = int(example_id[:8], 16) % 100
    if bucket < 85:
        return "train"
    if bucket < 95:
        return "validation"
    return "holdout"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "atena_evolution" / "training" / "distillation")
    parser.add_argument("--input", action="append", type=Path, dest="inputs")
    parser.add_argument("--min-holdout", type=int, default=5)
    args = parser.parse_args()

    inputs = args.inputs or DEFAULT_INPUTS
    candidates: list[dict[str, Any]] = []
    for path in inputs:
        path = path if path.is_absolute() else ROOT / path
        for item in read_jsonl(path):
            record = normalize(item, path)
            if record:
                candidates.append(record)

    unique: dict[str, dict[str, Any]] = {}
    for record in candidates:
        unique.setdefault(record["example_id"], record)
    records = list(unique.values())
    records.sort(key=lambda value: value["example_id"])
    splits = {"train": [], "validation": [], "holdout": []}
    for record in records:
        splits[split_name(record["example_id"])].append(record)

    # Mantém a divisão por hash como regra principal, mas garante conjuntos
    # mínimos em datasets pequenos sem duplicar exemplos.
    if len(records) < args.min_holdout + 2:
        raise SystemExit(f"dataset pequeno demais: {len(records)}; mínimo: {args.min_holdout + 2}")
    while len(splits["holdout"]) < args.min_holdout and len(splits["train"]) > 1:
        splits["holdout"].append(splits["train"].pop())
    if not splits["validation"] and len(splits["train"]) > 1:
        splits["validation"].append(splits["train"].pop())
    if len(splits["holdout"]) < args.min_holdout:
        raise SystemExit(f"holdout insuficiente: {len(splits['holdout'])}; mínimo exigido: {args.min_holdout}")
    if not splits["train"]:
        raise SystemExit("dataset de treino vazio")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        output = args.output_dir / f"{name}.jsonl"
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    domains: dict[str, int] = {}
    for row in records:
        domains[row["domain"]] = domains.get(row["domain"], 0) + 1
    manifest_inputs = []
    for input_path in inputs:
        resolved = input_path if input_path.is_absolute() else ROOT / input_path
        try:
            manifest_inputs.append(str(resolved.relative_to(ROOT)))
        except ValueError:
            manifest_inputs.append(str(resolved))
    manifest = {
        "status": "ok",
        "total": len(records),
        "splits": {name: len(rows) for name, rows in splits.items()},
        "domains": dict(sorted(domains.items())),
        "sources": len({row["source_url"] for row in records}),
        "curated": sum(row["source_type"] == "curated" for row in records),
        "web": sum(row["source_type"] == "web" for row in records),
        "inputs": manifest_inputs,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
