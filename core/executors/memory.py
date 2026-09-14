"""Executor somente leitura para a memória episódica e base de conhecimento."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.knowledge_base import KnowledgeBase
from core.memory_retrieval import retrieve_hybrid_context


class MemorySearchExecutor:
    """Busca memória sem alterar o banco de dados."""

    def __init__(self, db_path: str | Path, *, max_limit: int = 10, max_chars: int = 12_000) -> None:
        self.db_path = Path(db_path)
        self.max_limit = max(1, min(max_limit, 50))
        self.max_chars = max(1_000, max_chars)

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query de memória vazia")
        requested_limit = int(arguments.get("limit", 5))
        limit = max(1, min(requested_limit, self.max_limit))

        hybrid = retrieve_hybrid_context(self.db_path, query, limit=limit)
        episodes = hybrid["episodes"]
        documents = hybrid["knowledge_documents"]

        # O executor retorna somente dados serializáveis e limita o contexto
        # antes que ele seja incorporado ao prompt do modelo.
        result = {
            "query": query,
            "episodes": episodes,
            "knowledge_documents": documents,
            "source": "sqlite",
            "read_only": True,
            "context_policy": {
                "ranking": hybrid["ranking"],
                "provenance_required": hybrid["provenance_required"],
            },
        }
        serialized = str(result)
        if len(serialized) > self.max_chars:
            result["episodes"] = episodes[: max(1, limit // 2)]
            result["knowledge_documents"] = documents[: max(1, limit // 2)]
            result["truncated"] = True
        else:
            result["truncated"] = False
        result["evidence"] = [
            f"memory://sqlite/{self.db_path.name}?query={query[:80]}"
        ]
        return result
