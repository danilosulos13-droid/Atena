import json

from core.episodic_memory import build_episode
from core.memory_store import MemoryStore
from scripts.atena_scheduled_cycle import parse_model_json


def test_parse_structured_insight_requires_evidence_fields():
    value = parse_model_json(json.dumps({"insights": [{"text": "fato", "evidence_refs": ["mem-source"], "type": "fact", "confidence": 0.7}], "risks": [], "proposed_changes": [], "next_cycle": []}))
    assert value["insights"][0]["evidence_refs"] == ["mem-source"]
    assert value["insights"][0]["confidence"] == 0.7


def test_promote_supported_episode_updates_confidence(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with MemoryStore(db) as store:
        source_a = store.append(build_episode(record_type="observation", task_id="research:t", domain="science", output="evidence A", source_type="external_source", source_id="source:a", system_version="test"))
        source_b = store.append(build_episode(record_type="observation", task_id="research:t", domain="science", output="evidence B", source_type="external_source", source_id="source:b", system_version="test"))
        claim = store.append(build_episode(record_type="outcome", task_id="scheduled-learning-cycle", domain="self_evolution", output="claim", source_type="llm", source_id="cycle:test", system_version="test"))
        store.link_evidence(claim, source_a, "supports", 0.7)
        store.link_evidence(claim, source_b, "supports", 0.7)
        assert store.promote_from_evidence(claim, min_sources=2, confirm_sources=3) == "supported"
        row = store.connection.execute("SELECT status, confidence FROM episodes WHERE id=?", (claim,)).fetchone()
        assert row[0] == "supported"
        assert row[1] > 0.0


def test_parse_without_evidence_forces_limitation_and_zero_confidence():
    value = parse_model_json(json.dumps({"insights": [{"text": "alegação sem fonte", "evidence_refs": ["  ", ""], "type": "fact", "confidence": 0.95}], "risks": [], "proposed_changes": [], "next_cycle": []}))
    insight = value["insights"][0]
    assert insight["evidence_refs"] == []
    assert insight["type"] == "limitation"
    assert insight["confidence"] == 0.0


def test_legacy_string_insight_is_limitation():
    value = parse_model_json(json.dumps({"insights": ["texto legado"], "risks": [], "proposed_changes": [], "next_cycle": []}))
    assert value["insights"] == [{"text": "texto legado", "evidence_refs": [], "type": "limitation", "confidence": 0.0}]


def test_malformed_proposed_change_is_discarded_without_aborting_cycle():
    value = parse_model_json(json.dumps({
        "insights": [],
        "risks": [],
        "proposed_changes": [{"file": "scripts/example.py"}, {"file": "ok.py", "rationale": "motivo", "tests": ["pytest"]}],
        "next_cycle": [],
    }))
    assert value["proposed_changes"] == [{"file": "ok.py", "rationale": "motivo", "tests": ["pytest"]}]
    assert any("descartadas" in item for item in value["risks"])
