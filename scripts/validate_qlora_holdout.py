#!/usr/bin/env python3
"""Valida um adaptador QLoRA no holdout antes da promoção.

Compara a loss média do modelo-base com a loss do mesmo modelo + adaptador.
Retorna código 0 em ``pass`` ou ``skipped`` e código 1 em ``fail``/``blocked``.
O script não promove arquivos nem altera o modelo ativo.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
from typing import Any


def load_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("messages"), list):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def render(messages: list[dict[str, str]]) -> str:
    return "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in messages)


def evaluate(model_name: str, adapter: Path | None, rows: list[dict[str, Any]], max_length: int) -> dict[str, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=quantization, device_map="auto")
    if adapter is not None:
        model = PeftModel.from_pretrained(model, str(adapter), is_trainable=False)
    model.eval()
    device = next(model.parameters()).device
    losses: list[float] = []
    domains: dict[str, list[float]] = {}
    with torch.inference_mode():
        for row in rows:
            encoded = tokenizer(render(row["messages"]), return_tensors="pt", truncation=True, max_length=max_length)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            result = model(**encoded, labels=encoded["input_ids"])
            loss = float(result.loss.detach().float().cpu())
            if math.isfinite(loss):
                losses.append(loss)
                domains.setdefault(str(row.get("domain", "general")), []).append(loss)
    del model, tokenizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    mean = sum(losses) / len(losses) if losses else float("nan")
    return {
        "examples": len(losses),
        "loss": mean,
        "perplexity": math.exp(min(mean, 20.0)) if math.isfinite(mean) else None,
        "by_domain": {key: sum(values) / len(values) for key, values in sorted(domains.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--max-examples", type=int, default=256)
    parser.add_argument("--min-improvement", type=float, default=0.02)
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()

    if not args.adapter.is_dir() or not (args.adapter / "adapter_model.safetensors").exists():
        result = {"status": "blocked", "reason": f"adaptador inválido: {args.adapter}"}
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if not args.holdout.exists():
        result = {"status": "blocked", "reason": f"holdout ausente: {args.holdout}"}
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    import torch
    if not torch.cuda.is_available() and not args.allow_cpu:
        result = {"status": "blocked", "reason": "CUDA obrigatória para a validação QLoRA"}
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    rows = load_rows(args.holdout, args.max_examples)
    if len(rows) < 5:
        result = {"status": "blocked", "reason": f"holdout insuficiente: {len(rows)}; mínimo 5"}
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    baseline = evaluate(args.base_model, None, rows, args.max_length)
    candidate = evaluate(args.base_model, args.adapter, rows, args.max_length)
    improvement = (baseline["loss"] - candidate["loss"]) / max(abs(baseline["loss"]), 1e-9)
    passed = math.isfinite(improvement) and improvement >= args.min_improvement
    result = {
        "status": "pass" if passed else "fail",
        "base_model": args.base_model,
        "adapter": str(args.adapter.resolve()),
        "holdout": str(args.holdout.resolve()),
        "holdout_examples": len(rows),
        "baseline": baseline,
        "candidate": candidate,
        "improvement": improvement,
        "min_improvement": args.min_improvement,
        "promotion_allowed": passed,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
