from core.learning_progress import LearningProgress


def test_learning_progress_records_cycles_and_trend(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with LearningProgress(db) as progress:
        progress.record_cycle(
            cycle_id="cycle-1", model="test", benchmark_version="fixed-v1",
            benchmark_score=0.60, evidence_count=2, validated_lesson_count=0,
            lessons_consulted_count=0, regression_status="pass",
        )
        progress.record_cycle(
            cycle_id="cycle-2", model="test", benchmark_version="fixed-v1",
            benchmark_score=0.70, evidence_count=3, validated_lesson_count=1,
            lessons_consulted_count=1, regression_status="pass",
        )
        trend = progress.trend("fixed-v1")
        assert trend["decision"] == "improved"
        assert trend["delta"] == 0.1
        assert trend["samples"] == 2


def test_learning_progress_blocks_regression(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with LearningProgress(db) as progress:
        progress.record_cycle(cycle_id="cycle-1", benchmark_version="fixed-v1", benchmark_score=0.8)
        progress.record_cycle(cycle_id="cycle-2", benchmark_version="fixed-v1", benchmark_score=0.7, regression_status="fail")
        trend = progress.trend("fixed-v1")
        assert trend["decision"] == "regressed"
        assert trend["regression_failures"] == 1


def test_learning_progress_records_lesson_usage(tmp_path):
    db = tmp_path / "memory.sqlite3"
    lessons = [{"lesson": {"lesson_id": "lesson-1"}}, {"lesson": {"lesson_id": "lesson-2"}}]
    with LearningProgress(db) as progress:
        assert progress.record_lesson_usage("cycle-1", "memória histórica", lessons) == 2
        assert progress.counts()["lesson_usage_records"] == 2


def test_learning_progress_benchmark_summary_tracks_baseline_and_regression(tmp_path):
    db = tmp_path / "memory.sqlite3"
    with LearningProgress(db) as progress:
        progress.record_cycle(
            cycle_id="cycle-1", model="test", benchmark_version="fixed-v1",
            benchmark_score=0.60, evidence_count=2, validated_lesson_count=1,
            lessons_consulted_count=1, regression_status="pass",
            payload={"prompt_version": "p1", "task_hash": "hash-1", "seed": 7},
        )
        progress.record_cycle(
            cycle_id="cycle-2", model="test", benchmark_version="fixed-v1",
            benchmark_score=0.72, evidence_count=2, validated_lesson_count=2,
            lessons_consulted_count=2, regression_status="pass",
            payload={"prompt_version": "p1", "task_hash": "hash-1", "seed": 7},
        )
        progress.record_cycle(
            cycle_id="cycle-3", model="test", benchmark_version="fixed-v1",
            benchmark_score=0.68, evidence_count=2, validated_lesson_count=2,
            lessons_consulted_count=2, regression_status="fail",
            payload={"prompt_version": "p2", "task_hash": "hash-2", "seed": 9},
        )

        summary = progress.benchmark_summary("fixed-v1")
        assert summary["samples"] == 3
        assert summary["first_score"] == 0.6
        assert summary["last_score"] == 0.68
        assert summary["best_score"] == 0.72
        assert summary["regression_failures"] == 1
        assert summary["decision"] in {"mixed", "regressed"}
