from __future__ import annotations

import json

import core.atena_api_swarm_neurocausal_fabric as fabric_module
from core.atena_api_swarm_neurocausal_fabric import (
    ApiSwarmNeuroCausalFabric,
    SwarmTask,
    write_reports,
)


def test_fabric_assigns_ranked_api_with_causal_trace(monkeypatch):
    monkeypatch.setattr(
        fabric_module,
        "rank_api_candidates",
        lambda topic, limit=5: [
            {
                "name": "GitHub",
                "endpoint": "https://api.github.com",
                "category": "code",
                "score": 0.94,
            },
            {
                "name": "GitLab",
                "endpoint": "https://gitlab.com/api/v4",
                "category": "code",
                "score": 0.86,
            },
        ],
    )

    payload = ApiSwarmNeuroCausalFabric().run(
        [
            SwarmTask(
                task_id="child-code-001",
                description="buscar repositórios github",
                child_agent="child-code",
                required_capabilities=("code", "github"),
            )
        ]
    )

    assert payload["status"] == "ok"
    assert payload["approved_plans"] == 1
    plan = payload["plans"][0]
    assert plan["selected_api"]["name"] == "GitHub"
    assert plan["alternatives"][0]["name"] == "GitLab"
    assert plan["causal_trace"]["confidence"] >= 0.94
    assert plan["avoided_energy_units"] > 0


def test_write_reports_persists_json_and_markdown(tmp_path):
    payload = {
        "technology": "Atena API Swarm NeuroCausal Fabric",
        "status": "ok",
        "tasks_planned": 1,
        "approved_plans": 1,
        "average_confidence": 0.9,
        "avoided_energy_units": 0.42,
        "plans": [
            {
                "task_id": "t1",
                "child_agent": "child",
                "selected_api": {"name": "GitHub", "endpoint": "https://api.github.com"},
                "validation": "approved",
                "causal_trace": {"confidence": 0.9, "risk_reduced": "menos tentativa/erro"},
            }
        ],
    }

    json_path, md_path = write_reports(payload, tmp_path / "run.json", tmp_path / "run.md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "ok"
    content = md_path.read_text(encoding="utf-8")
    assert "Atena API Swarm NeuroCausal Fabric" in content
    assert "GitHub" in content
