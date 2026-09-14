from __future__ import annotations

import json
from pathlib import Path

from core import nanorobotics_learning as learning


def test_config_contains_public_sources_with_valid_weights() -> None:
    sources = learning.load_config()
    assert len(sources) >= 15
    assert {source["name"] for source in sources} >= {"PubMed", "Europe PMC", "arXiv", "FDA Nanotechnology"}
    assert all(0.0 <= source["weight"] <= 1.0 for source in sources)
    assert all(source["url"].startswith(("http://", "https://")) for source in sources)


def test_evidence_serialization_includes_safe_content() -> None:
    item = learning._evidence(
        {"name": "Test", "url": "https://example.org/api", "authority": "Example", "weight": 0.8},
        "nanorobotics",
        title="A study",
        url="https://example.org/paper",
        abstract="A short abstract about nanorobots.",
    )
    payload = item.to_dict()
    assert payload["content"] == "A study\nA short abstract about nanorobots."
    assert payload["url"] == "https://example.org/paper"
    assert "instruction" not in payload["content"].lower()


def test_fetch_source_reports_errors_without_raising(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise TimeoutError("offline")

    monkeypatch.setattr(learning, "_request_json", fail)
    source = {"name": "PubMed", "url": "https://example.org", "adapter": "pubmed", "weight": 0.9}
    result = learning.fetch_source(source, "nanorobotics", limit=2, timeout=1)
    assert result["ok"] is False
    assert result["items"] == []
    assert "TimeoutError" in result["error"]


def test_run_learning_indexes_evidence_and_writes_reports(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{"name": "Test API", "url": "https://example.org/api", "adapter": "crossref", "authority": "Example", "weight": 0.8, "enabled": True}]}), encoding="utf-8")

    monkeypatch.setattr(
        learning,
        "_request_json",
        lambda *args, **kwargs: {"message": {"items": [{"title": ["Nanorobot paper"], "URL": "https://doi.org/10/test", "abstract": "This abstract contains evidence about nanorobots and biomedical control."}]}},
    )
    payload = learning.run_learning(query="nanorobotics", config_path=config, db_path=tmp_path / "memory.sqlite3", output_dir=tmp_path / "reports", max_sources=1, limit_per_source=1, timeout=1)
    assert payload["status"] == "ok"
    assert payload["documents_added"] == 1
    assert Path(payload["report_json"]).exists()
    assert Path(payload["report_markdown"]).exists()
