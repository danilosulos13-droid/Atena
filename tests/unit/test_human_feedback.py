import importlib
import json


def test_feedback_is_idempotent_and_resolves_interaction(tmp_path, monkeypatch):
    module = importlib.import_module("core.human_feedback")
    interactions = tmp_path / "telegram_interactions.jsonl"
    feedback = tmp_path / "human_feedback.jsonl"
    monkeypatch.setattr(module, "INTERACTIONS_PATH", interactions)
    monkeypatch.setattr(module, "FEEDBACK_PATH", feedback)

    interaction_id = module.record_interaction(
        chat_id=123,
        message_id=7,
        prompt="pergunta",
        response="resposta",
    )
    first = module.record_feedback(interaction_id=interaction_id, label="approved", feedback_chat_id=123)
    second = module.record_feedback(interaction_id=interaction_id, label="approved", feedback_chat_id=123)

    assert first["label"] == "approved"
    assert second["id"] == first["id"]
    assert len(feedback.read_text(encoding="utf-8").splitlines()) == 1


def test_human_feedback_builds_preference_pair(tmp_path, monkeypatch):
    import core.autonomous_learning as learning

    monkeypatch.setattr(learning, "DATASET_DIR", tmp_path)
    ledger = learning.ExperienceLedger(tmp_path / "experiences.jsonl")
    feedback_path = tmp_path / "human_feedback.jsonl"
    feedback_path.write_text(
        json.dumps({"prompt": "p", "response": "boa", "label": "approved"}) + "\n"
        + json.dumps({"prompt": "p", "response": "ruim", "label": "rejected"}) + "\n",
        encoding="utf-8",
    )

    result = learning.build_datasets(ledger)
    rows = [json.loads(line) for line in (tmp_path / "preferences.jsonl").read_text().splitlines()]

    assert result["preferences"] == 1
    assert rows[0]["chosen"] == "boa"
    assert rows[0]["rejected"] == "ruim"
