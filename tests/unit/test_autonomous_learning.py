from pathlib import Path

from core.autonomous_learning import Experience, ExperienceLedger, build_datasets


def test_experience_id_is_stable():
    a = Experience("p", "r", 0.8, "test")
    b = Experience("p", "r", 0.8, "test")
    assert a.id == b.id


def test_ledger_is_idempotent(tmp_path: Path):
    ledger = ExperienceLedger(tmp_path / "experiences.jsonl")
    sample = Experience("p", "r", 0.9, "test")
    assert ledger.append(sample) is True
    assert ledger.append(sample) is False
    assert len(ledger.all()) == 1


def test_dataset_builder_does_not_invent_preferences(tmp_path: Path, monkeypatch):
    import core.autonomous_learning as al
    monkeypatch.setattr(al, "DATASET_DIR", tmp_path)
    ledger = ExperienceLedger(tmp_path / "experiences.jsonl")
    ledger.append(Experience("p", "good", 0.9, "test"))
    result = build_datasets(ledger)
    assert result["sft"] == 1
    assert result["preferences"] == 0
