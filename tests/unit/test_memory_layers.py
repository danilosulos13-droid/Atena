from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.memory_layers import AppendOnlyMemoryStore


def test_learning_cycle_writes_episodic_and_candidate_without_overwrite(tmp_path: Path) -> None:
    store = AppendOnlyMemoryStore(tmp_path / "memory")
    payload = {
        "status": "ok",
        "summary": "Sinal consolidável",
        "confidence": 0.62,
        "sources": [
            {"title": "Fonte A", "url": "https://example.test/a", "summary": "Evidência A"},
            {"title": "Fonte B", "url": "https://example.test/b", "summary": "Evidência B"},
        ],
    }
    result = store.record_learning_cycle("agent memory", payload, [{"plugin_path": "plugins/x.json"}])
    candidate = Path(result["semantic_candidate"]["path"])
    assert candidate.is_file()
    data = json.loads(candidate.read_text(encoding="utf-8"))
    assert data["status"] == "candidate"
    assert data["sources"][0]["url"] == "https://example.test/a"
    assert data["validation"]["passed"] is False
    lines = store.ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "candidate_created"


def test_existing_candidate_is_not_overwritten(tmp_path: Path) -> None:
    store = AppendOnlyMemoryStore(tmp_path / "memory")
    first = store.add_candidate({"topic": "memory", "claim": "same", "sources": []})
    second = store.add_candidate({"topic": "memory", "claim": "same", "sources": []})
    assert first["path"] == second["path"]
    assert len(list((tmp_path / "memory" / "semantic_candidates").glob("*.json"))) == 1
    assert len(store.ledger_path.read_text(encoding="utf-8").splitlines()) == 2


def test_promotion_requires_passed_validation_and_preserves_candidate(tmp_path: Path) -> None:
    store = AppendOnlyMemoryStore(tmp_path / "memory")
    candidate = store.add_candidate({"topic": "memory", "claim": "claim", "sources": []})
    with pytest.raises(ValueError):
        store.promote_validated(candidate["knowledge_id"], {"passed": False}, "human-review")
    promoted = store.promote_validated(
        candidate["knowledge_id"],
        {"passed": True, "benchmark_cases": ["memory-01"]},
        "human-review",
    )
    assert Path(promoted["path"]).is_file()
    assert Path(candidate["path"]).is_file()
    assert len(list((tmp_path / "memory" / "semantic_validated").glob("*.json"))) == 1
    assert len(store.ledger_path.read_text(encoding="utf-8").splitlines()) == 2
