from pathlib import Path

from core.knowledge_base import KnowledgeBase


def test_dedup_and_search(tmp_path: Path):
    db = tmp_path / "knowledge.sqlite3"
    with KnowledgeBase(db) as kb:
        first = kb.add_document(url="https://example.com/a#x", title="A", topic="direito", content="Responsabilidade civil depende de dano e nexo causal.")
        second = kb.add_document(url="https://example.com/a", title="A", topic="direito", content="Responsabilidade civil depende de dano e nexo causal.")
        assert first[2] is True
        assert second[2] is False
        hits = kb.search("responsabilidade civil")
        assert hits and hits[0]["url"] == "https://example.com/a#x".replace("#x", "")
