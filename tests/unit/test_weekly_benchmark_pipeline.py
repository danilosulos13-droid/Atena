from scripts.weekly_evolution_benchmark import build_rotation_manifest


def test_build_rotation_manifest_uses_seed_and_outputs():
    manifest = build_rotation_manifest(seed=42, count=6, model="llama3.2", output_dir="tmp/weeklies")

    assert manifest["seed"] == 42
    assert manifest["count"] == 6
    assert manifest["model"] == "llama3.2"
    assert manifest["cases_path"].endswith("rotating_cases_seed_42.json")
    assert manifest["output_dir"].endswith("tmp/weeklies")
