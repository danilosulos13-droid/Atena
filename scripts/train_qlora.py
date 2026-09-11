#!/usr/bin/env python3
"""Treina um adaptador QLoRA 4-bit em uma GPU NVIDIA.

Este script nunca tenta treinar silenciosamente em CPU: CUDA é requisito para o
job de produção. O modelo-base permanece separado do adaptador salvo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("ATENA_QLORA_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"))
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=int(os.getenv("ATENA_QLORA_MAX_LENGTH", "512")))
    parser.add_argument("--epochs", type=float, default=float(os.getenv("ATENA_QLORA_EPOCHS", "1")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("ATENA_QLORA_BATCH_SIZE", "1")))
    parser.add_argument("--gradient-accumulation", type=int, default=int(os.getenv("ATENA_QLORA_GRADIENT_ACCUMULATION", "8")))
    args = parser.parse_args()

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, DataCollatorForLanguageModeling, Trainer, TrainingArguments
    except ImportError as exc:
        raise SystemExit(f"dependência QLoRA ausente: {exc}")

    if not torch.cuda.is_available():
        raise SystemExit("GPU CUDA obrigatória: torch.cuda.is_available() retornou False")
    if not args.train.exists():
        raise SystemExit(f"dataset ausente: {args.train}")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization,
        device_map="auto",
    )
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=int(os.getenv("ATENA_QLORA_R", "16")),
        lora_alpha=int(os.getenv("ATENA_QLORA_ALPHA", "32")),
        lora_dropout=float(os.getenv("ATENA_QLORA_DROPOUT", "0.05")),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=os.getenv("ATENA_QLORA_TARGET_MODULES", "q_proj,k_proj,v_proj,o_proj").split(","),
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    model.config.use_cache = False

    rows = load_dataset("json", data_files=str(args.train), split="train")

    def tokenize(batch: dict[str, list]) -> dict[str, list]:
        texts = []
        for messages in batch["messages"]:
            texts.append("\n".join(f"{m['role']}: {m['content']}" for m in messages))
        return tokenizer(texts, truncation=True, max_length=args.max_length, padding=False)

    tokenized = rows.map(tokenize, batched=True, remove_columns=rows.column_names)
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    args.output.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=float(os.getenv("ATENA_QLORA_LR", "2e-4")),
        logging_steps=1,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        report_to=[],
        fp16=dtype == torch.float16,
        bf16=dtype == torch.bfloat16,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
    )
    try:
        trainer = Trainer(model=model, args=training_args, train_dataset=tokenized, data_collator=collator, processing_class=tokenizer)
    except TypeError as exc:
        if "processing_class" not in str(exc):
            raise
        trainer = Trainer(model=model, args=training_args, train_dataset=tokenized, data_collator=collator, tokenizer=tokenizer)
    trainer.train()
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    manifest = {
        "status": "candidate",
        "base_model": args.model,
        "examples": len(rows),
        "output": str(args.output),
        "cuda_device": torch.cuda.get_device_name(0),
        "dtype": str(dtype),
        "quantization": "nf4-4bit",
    }
    (args.output / "qlora_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
