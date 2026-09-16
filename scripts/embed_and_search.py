"""Gera embeddings de 384 dimensões compatíveis com atena_memory_chunks.

Modelo padrão: sentence-transformers/all-MiniLM-L6-v2.
PEFT é opcional: só carregue um adapter treinado especificamente sobre este
encoder, não um adapter LoRA do Qwen/Qwen2.5-0.5B-Instruct.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

try:
    from peft import PeftModel
except ImportError:  # PEFT é opcional para inferência do encoder base.
    PeftModel = None  # type: ignore[assignment,misc]


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EXPECTED_DIMENSION = 384


def mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked = last_hidden_state * mask
    return masked.sum(dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)


def load_encoder(model_name: str = DEFAULT_MODEL, adapter_path: str | None = None):
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    encoder = AutoModel.from_pretrained(model_name)

    if adapter_path:
        if PeftModel is None:
            raise RuntimeError("Instale peft para carregar um adapter LoRA.")
        # O adapter precisa ter sido treinado para o mesmo encoder e tokenizer.
        encoder = PeftModel.from_pretrained(encoder, adapter_path)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    encoder.to(device)
    encoder.eval()
    return tokenizer, encoder, device


def embed_texts(
    texts: list[str],
    tokenizer,
    encoder,
    device: torch.device,
) -> np.ndarray:
    with torch.inference_mode():
        batch = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        ).to(device)
        output = encoder(**batch)
        pooled = mean_pool(output.last_hidden_state, batch["attention_mask"])
        # Normalização L2 torna o produto interno equivalente à similaridade
        # cosseno usada pelo operador <=> do pgvector.
        embeddings = torch.nn.functional.normalize(pooled, p=2, dim=1)

    result = embeddings.detach().cpu().numpy().astype(np.float32)
    if result.shape[1] != EXPECTED_DIMENSION:
        raise ValueError(
            f"Dimensão incompatível: {result.shape[1]}; esperada {EXPECTED_DIMENSION}."
        )
    return result


def search_supabase(
    tenant_id: str,
    query_text: str,
    query_embedding: np.ndarray,
    match_count: int = 10,
    approved_only: bool = False,
) -> list[dict[str, Any]]:
    from supabase import create_client

    url = os.environ["ATENA_SUPABASE_URL"]
    key = os.environ["ATENA_SUPABASE_KEY"]
    client = create_client(url, key)
    response = client.rpc(
        "search_atena_memory_hybrid",
        {
            "p_tenant_id": tenant_id,
            "p_query_embedding": query_embedding[0].tolist(),
            "p_query_text": query_text,
            "p_match_count": match_count,
            "p_vector_weight": 0.7,
            "p_text_weight": 0.3,
            "p_approved_only": approved_only,
        },
    ).execute()
    return response.data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--approved-only", action="store_true")
    args = parser.parse_args()

    tokenizer, encoder, device = load_encoder(args.model, args.adapter)
    embedding = embed_texts([args.text], tokenizer, encoder, device)
    print({
        "model": args.model,
        "device": str(device),
        "shape": list(embedding.shape),
        "dimension": int(embedding.shape[1]),
        "embedding": embedding[0].tolist(),
    })

    if args.search:
        for row in search_supabase(
            args.tenant_id,
            args.text,
            embedding,
            approved_only=args.approved_only,
        ):
            print(row)


if __name__ == "__main__":
    main()
