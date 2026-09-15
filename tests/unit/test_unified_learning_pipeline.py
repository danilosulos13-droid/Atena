from __future__ import annotations

import json
from pathlib import Path

from scripts.unified_learning_pipeline import main
from core.memory_store import MemoryStore


def test_unified_ingest_records_provenance_and_is_idempotent(tmp_path, monkeypatch):
    source = tmp_path / "research.jsonl"
    source.write_text(
        json.dumps(
            {
                "topic": "IA",
                "title": "Fonte de teste",
                "source_url": "https://example.test/article",
                "payload": {"full_text": "Texto de evidência suficientemente longo para criar um episódio auditável, preservar a proveniência e formar um exemplo de treinamento válido."},
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps({"title": "sem url", "payload": {"full_text": "deve ser rejeitado"}})
        + "\n",
        encoding="utf-8",
    )
    db = tmp_path / "memory.sqlite3"
    experiences = tmp_path / "experiences.jsonl"
    report = tmp_path / "report.json"
    args = [
        "unified_learning_pipeline.py",
        "ingest",
        "--input",
        str(source),
        "--db",
        str(db),
        "--experiences",
        str(experiences),
        "--report",
        str(report),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    first = json.loads(report.read_text(encoding="utf-8"))
    assert first["episodes_created"] == 1
    assert first["examples_created"] == 1
    assert first["rejected"] == 1

    assert main() == 0
    second = json.loads(report.read_text(encoding="utf-8"))
    assert second["episodes_existing"] == 1
    assert second["examples_created"] == 0

    with MemoryStore(db) as store:
        assert store.count() == 1
        assert store.verify_integrity()
        record = store.get(first["memory_ids"][0])
        assert record is not None
        assert record["provenance"]["source_url"] == "https://example.test/article"
        assert record["evidence"]["status"] == "supported"
