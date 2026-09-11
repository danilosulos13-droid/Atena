from __future__ import annotations

import json
from pathlib import Path

from scripts.integration_healthcheck import ROOT, run_healthcheck


def test_healthcheck_is_read_only_and_has_expected_schema():
    report = run_healthcheck()
    assert report["network_calls"] is False
    assert report["external_side_effects"] is False
    assert report["schema_version"] == "1.0"
    assert report["required_failure_count"] == 0
    assert report["checks"]
    assert {item["status"] for item in report["checks"]} <= {"healthy", "degraded", "blocked", "failed", "skipped"}


def test_healthcheck_covers_core_layers_and_workflows():
    report = run_healthcheck()
    layers = {item["layer"] for item in report["checks"]}
    assert {"core", "learning", "benchmark", "telegram", "news", "games", "monitoring", "workflows"} <= layers
    workflow_names = {item["name"] for item in report["checks"] if item["layer"] == "workflows"}
    assert {"atena-ci", "news", "games", "regression", "selfmod"} <= workflow_names


def test_healthcheck_does_not_require_external_credentials(monkeypatch):
    for name in ("ATENA_TELEGRAM_BOT_TOKEN", "ATENA_TELEGRAM_CHAT_ID", "ATENA_X_BEARER_TOKEN", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    report = run_healthcheck()
    assert report["required_failure_count"] == 0
    optional = [item for item in report["checks"] if item["layer"] == "integrations"]
    assert optional
    assert all(item["required"] is False for item in optional)


def test_report_can_be_serialized(tmp_path: Path):
    report = run_healthcheck()
    output = tmp_path / "healthcheck.json"
    output.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["decision"] in {"healthy", "degraded", "failed"}
