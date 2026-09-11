import json
from pathlib import Path

from scripts.upload_learning_to_drive import category_for_path, collect_items, main


def test_category_routes_learning_artifacts():
    assert category_for_path(Path("atena_evolution/training/sft.jsonl")) == "Aprendizagens"
    assert category_for_path(Path("atena_evolution/model_promotion_state.json")) == "Memórias"
    assert category_for_path(Path("artifacts/learning-audio/report.ogg")) == "Áudios"
    assert category_for_path(Path("atena_evolution/models/candidate/adapter.safetensors")) == "Modelos"
    assert category_for_path(Path("atena_evolution/training/latest_workflow_result.json")) == "Relatórios"


def test_collect_items_deduplicates_and_expands_directories(tmp_path: Path):
    folder = tmp_path / "training"
    folder.mkdir()
    first = folder / "a.jsonl"
    second = folder / "b.jsonl"
    first.write_text("a\n", encoding="utf-8")
    second.write_text("b\n", encoding="utf-8")

    items = collect_items([first, folder], [])

    assert [item.name for item in items] == ["a.jsonl", "b.jsonl"]
    assert all(item.category == "Relatórios" for item in items)


def test_dry_run_does_not_require_google_credentials(tmp_path: Path, capsys):
    report = tmp_path / "latest.json"
    report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")

    code = main([
        "--folder-id", "folder-id",
        "--report", str(report),
        "--dry-run",
    ])

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "dry-run"
    assert output["items"][0]["category"] == "Relatórios"
