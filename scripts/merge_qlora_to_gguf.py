#!/usr/bin/env python3
"""Faz merge de um adaptador PEFT/QLoRA e exporta o modelo para GGUF.

O merge deve carregar o modelo-base em FP16/BF16, não em 4-bit. A quantização
4-bit é adequada para treino/inferência, mas não é o formato correto para
fundir os deltas LoRA com precisão. A conversão GGUF usa o script oficial do
llama.cpp e, opcionalmente, o binário llama-quantize.

Exemplo:
  python scripts/merge_qlora_to_gguf.py \
    --base-model Qwen/Qwen2.5-1.5B-Instruct \
    --adapter atena_evolution/models/qlora-1.5b-candidate \
    --merged-dir /opt/atena/merged-1.5b \
    --gguf /opt/atena/atena-1.5b-f16.gguf \
    --llama-cpp /opt/llama.cpp \
    --quantize Q4_K_M \
    --quantized-gguf /opt/atena/atena-1.5b-Q4_K_M.gguf
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def command_exists(path: str) -> bool:
    return Path(path).exists() or shutil.which(path) is not None


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--merged-dir", type=Path, required=True)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--llama-cpp", type=Path, required=True, help="checkout do llama.cpp")
    parser.add_argument("--outtype", default="f16", choices=["f16", "f32"])
    parser.add_argument("--quantize", default="", help="ex.: Q4_K_M; vazio não quantiza")
    parser.add_argument("--quantized-gguf", type=Path)
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.adapter.is_dir():
        raise SystemExit(f"adaptador inexistente: {args.adapter}")
    for required in ("adapter_config.json", "adapter_model.safetensors"):
        if not (args.adapter / required).exists():
            raise SystemExit(f"arquivo obrigatório ausente no adaptador: {required}")
    converter = args.llama_cpp / "convert_hf_to_gguf.py"
    if not converter.exists():
        raise SystemExit(f"conversor não encontrado: {converter}")
    if args.quantize and not args.quantized_gguf:
        raise SystemExit("--quantize exige --quantized-gguf")
    if args.merged_dir.exists() and any(args.merged_dir.iterdir()) and not args.force:
        raise SystemExit(f"diretório de merge não está vazio: {args.merged_dir}; use --force")

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(f"dependência ausente: {exc}")

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    if not torch.cuda.is_available():
        print("Aviso: merge sem CUDA pode exigir muita RAM e será lento.", file=sys.stderr)
        dtype = torch.float32

    args.merged_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=args.trust_remote_code)
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        low_cpu_mem_usage=True,
        trust_remote_code=args.trust_remote_code,
    )
    peft_model = PeftModel.from_pretrained(
        base,
        str(args.adapter),
        is_trainable=False,
    )
    if hasattr(peft_model, "load_adapter"):
        print("Adaptador carregado; executando merge_and_unload...", flush=True)
    merged = peft_model.merge_and_unload(safe_merge=True)
    merged.save_pretrained(args.merged_dir, safe_serialization=True, max_shard_size="2GB")
    tokenizer.save_pretrained(args.merged_dir)
    del merged, peft_model, base
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    args.gguf.parent.mkdir(parents=True, exist_ok=True)
    run([
        sys.executable,
        str(converter),
        str(args.merged_dir),
        "--outfile", str(args.gguf),
        "--outtype", args.outtype,
    ])

    quantized = None
    if args.quantize:
        quantizer_candidates = [
            args.llama_cpp / "build" / "bin" / "llama-quantize",
            args.llama_cpp / "bin" / "llama-quantize",
            Path(shutil.which("llama-quantize") or ""),
        ]
        quantizer = next((p for p in quantizer_candidates if str(p) and p.exists()), None)
        if quantizer is None:
            raise SystemExit("llama-quantize não encontrado; compile llama.cpp ou informe o binário no PATH")
        args.quantized_gguf.parent.mkdir(parents=True, exist_ok=True)
        run([str(quantizer), str(args.gguf), str(args.quantized_gguf), args.quantize])
        quantized = str(args.quantized_gguf)

    manifest = {
        "status": "merged",
        "base_model": args.base_model,
        "adapter": str(args.adapter.resolve()),
        "merged_dir": str(args.merged_dir.resolve()),
        "gguf": str(args.gguf.resolve()),
        "quantized_gguf": quantized,
        "outtype": args.outtype,
        "quantization": args.quantize or None,
    }
    manifest_path = args.gguf.with_suffix(args.gguf.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
