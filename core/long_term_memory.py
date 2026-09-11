"""Memória semântica persistente da Atena baseada em FAISS local."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

from modules.vector_memory import DistanceMetric, IndexConfig, IndexType, VectorMemory


class LongTermMemoryError(RuntimeError):
    pass


class LongTermMemory:
    def __init__(self, storage_path: str | Path = "atena_evolution/vector_memory", model_name: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise LongTermMemoryError("instale sentence-transformers para habilitar a memória vetorial") from exc
        self.encoder = SentenceTransformer(model_name or os.getenv("ATENA_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
        dimension = int(self.encoder.get_sentence_embedding_dimension())
        config = IndexConfig(index_type=IndexType.FAISS_FLAT, distance_metric=DistanceMetric.COSINE)
        self.memory = VectorMemory(dimension=dimension, storage_path=str(storage_path), config=config)

    def remember(self, text: str, *, metadata: dict[str, Any] | None = None, tags: list[str] | None = None, importance: float = 0.5) -> str:
        clean = str(text or "").strip()
        if not clean:
            raise LongTermMemoryError("texto vazio")
        vector = np.asarray(self.encoder.encode([clean], normalize_embeddings=True)[0], dtype="float32")
        return self.memory.add_experience(vector, {"text": clean, **(metadata or {})}, importance_score=max(0.0, min(1.0, importance)), tags=tags)

    def recall(self, query: str, *, top_k: int = 5, min_similarity: float = 0.25) -> list[dict[str, Any]]:
        clean = str(query or "").strip()
        if not clean:
            return []
        vector = np.asarray(self.encoder.encode([clean], normalize_embeddings=True)[0], dtype="float32")
        return [{"similarity": float(score), **entry.metadata, "id": entry.id} for entry, score in self.memory.search_similar(vector, top_k=top_k, min_similarity=min_similarity)]
