from __future__ import annotations

import json

from core.atena_meta_learner import EvolutionPattern, SelfReflectiveMetaLearner


def test_meta_learner_accepts_object_and_list_reports(tmp_path):
    (tmp_path / "object.json").write_text(json.dumps({"fitness": 75}), encoding="utf-8")
    (tmp_path / "list.json").write_text(
        json.dumps([{"score": 80}, {"best_fitness": 20}, "ignored"]),
        encoding="utf-8",
    )

    learner = SelfReflectiveMetaLearner(history_path=tmp_path / "logs")
    pattern = EvolutionPattern()
    learner._parse_json_reports(tmp_path, pattern)

    assert pattern.total_mutations == 3
    assert pattern.successful_mutations == 2
    assert pattern.fitness_history == [75.0, 80.0]
