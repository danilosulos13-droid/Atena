from pathlib import Path

from core.executors.memory import MemorySearchExecutor
from core.executors.web import WebSearchExecutor
from core.knowledge_base import KnowledgeBase


def test_memory_executor_reads_sqlite_knowledge_base(tmp_path: Path):
    db_path = tmp_path / "memory.sqlite3"
    with KnowledgeBase(db_path) as knowledge:
        knowledge.add_document(
            url="https://example.test/rollback",
            title="Rollback seguro",
            topic="segurança",
            content="O rollback deve ser validado em sandbox antes da promoção.",
        )
    result = MemorySearchExecutor(db_path)({"query": "rollback sandbox", "limit": 3})
    assert result["read_only"] is True
    assert result["source"] == "sqlite"
    assert result["knowledge_documents"]
    assert result["evidence"]


def test_web_executor_filters_domain_and_preserves_untrusted_boundary(monkeypatch):
    def fake_fetch(**kwargs):
        assert kwargs["mode"] == "autonomous"
        return [
            {
                "source": "authorized-feed",
                "category": "research",
                "ok": True,
                "items": [
                    {"title": "Permitido", "link": "https://allowed.test/a", "summary": "a", "content_hash": "h1"},
                    {"title": "Filtrado", "link": "https://other.test/b", "summary": "b", "content_hash": "h2"},
                ],
            }
        ]

    monkeypatch.setattr("core.executors.web.fetch_configured_sources", fake_fetch)
    result = WebSearchExecutor()( {"query": "pesquisa", "domain": "allowed.test"} )
    assert [item["title"] for item in result["items"]] == ["Permitido"]
    assert result["network"] is True
    assert result["untrusted_content"] is True
    assert result["evidence"] == ["https://allowed.test/a"]
