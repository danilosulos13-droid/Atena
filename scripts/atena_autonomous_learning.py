#!/usr/bin/env python3
"""CLI do ciclo de aprendizagem autônoma da ATENA.

Comandos:
  collect  -> coleta experiências e monta datasets
  train    -> executa SFT/LoRA opcional (ATENA_AUTOTRAIN=1 ou --train)
  cycle    -> coleta + treino + relatório; nunca promove sem avaliação
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.autonomous_learning import ARTIFACT_DIR, DATASET_DIR, run_collection_cycle, write_state
from core.model_candidate_evaluator import evaluate_and_maybe_promote


def _optional_train() -> dict[str, Any]:
    model_name = os.getenv("ATENA_TRAIN_MODEL", "").strip()
    if not model_name:
        return {"status": "skipped", "reason": "ATENA_TRAIN_MODEL não configurado"}
    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        return {"status": "skipped", "reason": f"dependência de treino ausente: {exc}"}

    sft_path = DATASET_DIR / "sft.jsonl"
    if not sft_path.exists() or sft_path.stat().st_size == 0:
        return {"status": "skipped", "reason": "dataset SFT vazio"}

    rows = load_dataset("json", data_files=str(sft_path), split="train")
    total_examples = len(rows)
    if total_examples < int(os.getenv("ATENA_MIN_TRAIN_EXAMPLES", "16")):
        return {"status": "skipped", "reason": "poucos exemplos para treino", "examples": len(rows)}
    max_examples = int(os.getenv("ATENA_MAX_TRAIN_EXAMPLES", "0"))
    if max_examples > 0:
        rows = rows.select(range(min(max_examples, len(rows))))

    # O mesmo holdout determinístico usado pelo avaliador não pode entrar no
    # treino; caso contrário a perplexidade do candidato fica otimista por
    # vazamento e um adapter ruim pode ser promovido.
    holdout_fraction = min(max(float(os.getenv("ATENA_HOLDOUT_FRACTION", "0.2")), 0.1), 0.4)
    holdout_ids = {
        str(row.get("id", ""))
        for row in rows
        if int(hashlib.sha256(str(row.get("id", "")).encode()).hexdigest()[:8], 16) % 10
        < max(1, round(holdout_fraction * 10))
    }
    train_rows = rows.filter(lambda row: str(row.get("id", "")) not in holdout_ids)
    if len(train_rows) < 4:
        return {
            "status": "skipped",
            "reason": "poucos exemplos restantes após separar holdout",
            "examples": total_examples,
            "holdout_examples": len(holdout_ids),
        }

    tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    max_length = int(os.getenv("ATENA_TRAIN_MAX_LENGTH", "1024"))

    def tokenize(batch: dict[str, list[Any]]) -> dict[str, Any]:
        texts = []
        for messages in batch["messages"]:
            rendered = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            texts.append(rendered)
        # Padding dinâmico: cada lote é preenchido apenas até sua maior sequência.
        return tokenizer(texts, truncation=True, max_length=max_length, padding=False)

    tokenized = train_rows.map(tokenize, batched=True, remove_columns=train_rows.column_names)
    # O collator cria labels e faz padding dinâmico no momento de cada lote.
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    base = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto")
    config = LoraConfig(
        r=int(os.getenv("ATENA_LORA_R", "16")),
        lora_alpha=int(os.getenv("ATENA_LORA_ALPHA", "32")),
        lora_dropout=float(os.getenv("ATENA_LORA_DROPOUT", "0.05")),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=os.getenv("ATENA_LORA_TARGET_MODULES", "q_proj,k_proj,v_proj,o_proj").split(","),
    )
    model = get_peft_model(base, config)
    model.config.use_cache = False

    output = ARTIFACT_DIR / "candidate"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(output),
        num_train_epochs=float(os.getenv("ATENA_TRAIN_EPOCHS", "1")),
        per_device_train_batch_size=int(os.getenv("ATENA_TRAIN_BATCH_SIZE", "1")),
        gradient_accumulation_steps=int(os.getenv("ATENA_GRAD_ACCUMULATION", "8")),
        learning_rate=float(os.getenv("ATENA_TRAIN_LR", "2e-4")),
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        fp16=bool(torch.cuda.is_available() and os.getenv("ATENA_FP16", "1") == "1"),
    )
    # Transformers recentes substituíram ``tokenizer`` por ``processing_class``;
    # manter fallback para versões anteriores usadas por instalações locais.
    try:
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized,
            data_collator=collator,
            processing_class=tokenizer,
        )
    except TypeError as exc:
        if "processing_class" not in str(exc):
            raise
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=tokenized,
            data_collator=collator,
            tokenizer=tokenizer,
        )
    # Mantém stdout reservado ao JSON final consumido pelo workflow; os logs
    # progressivos continuam visíveis no Actions via stderr.
    with contextlib.redirect_stdout(sys.stderr):
        trainer.train()
    model.save_pretrained(output)
    tokenizer.save_pretrained(output)
    manifest = {
        "status": "candidate",
        "base_model": model_name,
        "examples": len(train_rows),
        "total_examples": total_examples,
        "holdout_examples": len(holdout_ids),
        "path": str(output),
    }
    write_state(last_training=manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["collect", "train", "evaluate", "cycle"])
    parser.add_argument("--train", action="store_true", help="Permite treino no ciclo")
    args = parser.parse_args()

    if args.command == "evaluate":
        model_name = os.getenv("ATENA_TRAIN_MODEL", "").strip()
        if not model_name:
            result = {"evaluation": {"status": "blocked", "reason": "ATENA_TRAIN_MODEL não configurado"}}
        else:
            result = {"evaluation": evaluate_and_maybe_promote(base_model=model_name)}
        write_state(last_cycle=result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    collection = run_collection_cycle()
    result: dict[str, Any] = {"collection": collection}
    if args.command in {"train", "cycle"} and (args.train or os.getenv("ATENA_AUTOTRAIN") == "1"):
        result["training"] = _optional_train()
        if result["training"].get("status") == "candidate":
            model_name = os.getenv("ATENA_TRAIN_MODEL", "").strip()
            if model_name:
                result["evaluation"] = evaluate_and_maybe_promote(base_model=model_name).__dict__
    else:
        result["training"] = {"status": "skipped", "reason": "treino não habilitado"}
    write_state(last_cycle=result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
