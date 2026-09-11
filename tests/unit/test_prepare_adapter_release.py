import json

import scripts.prepare_adapter_release as release


def test_prepare_adapter_release_creates_manifest(tmp_path, monkeypatch):
    active = tmp_path / "models" / "active"
    releases = tmp_path / "models" / "releases"
    manifest = tmp_path / "models" / "active_manifest.json"
    active.mkdir(parents=True)
    (active / "adapter_config.json").write_text('{"r": 8}', encoding="utf-8")
    monkeypatch.setattr(release, "ACTIVE", active)
    monkeypatch.setattr(release, "RELEASES", releases)
    monkeypatch.setattr(release, "MANIFEST", manifest)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")

    assert release.main() == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["release_id"] == "42-abcdef123456"
    assert payload["files"][0]["path"] == "adapter_config.json"
    assert (releases / "42-abcdef123456" / "adapter_config.json").exists()
