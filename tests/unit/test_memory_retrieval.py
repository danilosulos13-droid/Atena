from core.episodic_memory import build_episode
from core.memory_retrieval import format_context, retrieve_context
from core.memory_store import MemoryStore


def test_retrieve_context_prioritizes_relevant_episode(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with MemoryStore(db) as store:
        first = build_episode(record_type="observation", task_id="t1", domain="quantum", output="correção de erros quânticos e evidência", source_type="benchmark", source_id="b1", system_version="test", status="supported", confidence=0.8)
        store.append(first)
        second = build_episode(record_type="observation", task_id="t2", domain="cooking", output="receita de bolo e forno", source_type="benchmark", source_id="b2", system_version="test")
        store.append(second)
    items = retrieve_context(db, "tecnologia quântica correção de erros", limit=3)
    assert items
    assert items[0]["episode_id"] == first["memory_id"]
    rendered = format_context(items)
    assert first["memory_id"] in rendered
    assert "correção de erros quânticos" in rendered
