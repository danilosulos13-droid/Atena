from __future__ import annotations

from core.executors.memory import MemorySearchExecutor
from core.knowledge_base import KnowledgeBase
from core.memory_retrieval import retrieve_hybrid_context


def test_hybrid_context_includes_document_provenance_without_mutation(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with KnowledgeBase(db) as knowledge:
        knowledge.add_document(
            url="https://pubmed.ncbi.nlm.nih.gov/example",
            title="Nanorobotics and artificial intelligence",
            topic="nanorobotics",
            content="Artificial intelligence improves adaptive nanorobot navigation and medical imaging.",
            metadata={"authority": "NIH", "weight": 0.98},
        )
        before = knowledge.stats()

    result = retrieve_hybrid_context(db, "artificial intelligence nanorobot", limit=3)

    assert result["read_only"] is True
    assert result["provenance_required"] is True
    assert result["knowledge_documents"]
    document = result["knowledge_documents"][0]
    assert document["provenance"]["source_url"].startswith("https://pubmed")
    assert document["evidence_score"] > 0
    with KnowledgeBase(db) as knowledge:
        assert knowledge.stats() == before


def test_memory_executor_exposes_context_policy_and_serializable_results(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with KnowledgeBase(db) as knowledge:
        knowledge.add_document(
            url="https://example.org/ai",
            title="AI research",
            topic="ai",
            content="Machine learning and language models.",
        )

    result = MemorySearchExecutor(db)(
        {"query": "machine learning", "limit": 2}
    )

    assert result["read_only"] is True
    assert result["context_policy"]["provenance_required"] is True
    assert result["knowledge_documents"]
