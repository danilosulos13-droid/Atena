from scripts.memory_identity_healthcheck import run


def test_memory_identity_healthcheck_is_safe(tmp_path):
    result = run(tmp_path)
    assert all(status == "ok" for status in result["imports"].values())
    assert result["episodic"]["ok"] is True
    assert result["identity"]["ok"] is True
    assert result["production_databases_modified"] is False
