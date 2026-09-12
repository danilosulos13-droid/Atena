from scripts.atena_scheduled_cycle import keep_current_evidence_refs


def test_keep_current_evidence_refs_drops_ids_from_previous_cycles():
    observations = {
        "insights": [
            {
                "text": "fato herdado sem prova atual",
                "evidence_refs": ["mem-old", "mem-current"],
                "type": "fact",
                "confidence": 0.9,
            }
        ]
    }
    result = keep_current_evidence_refs(observations, {"mem-current"})
    assert result["insights"][0]["evidence_refs"] == ["mem-current"]
    assert result["insights"][0]["type"] == "fact"


def test_keep_current_evidence_refs_downgrades_fact_without_current_source():
    observations = {
        "insights": [
            {
                "text": "fato sem evidência atual",
                "evidence_refs": ["mem-old"],
                "type": "fact",
                "confidence": 0.9,
            }
        ]
    }
    result = keep_current_evidence_refs(observations, {"mem-current"})
    insight = result["insights"][0]
    assert insight["evidence_refs"] == []
    assert insight["type"] == "limitation"
    assert insight["confidence"] == 0.0


def test_run_agent_validation_handles_null_observations(monkeypatch, tmp_path):
    import scripts.atena_scheduled_cycle as cycle

    class Agent:
        blueprint = type("Blueprint", (), {"allowed_tools": ("web.search",)})()

        def describe(self):
            return {"name": "fake"}

    class Master:
        def assign(self, _goal):
            return Agent()

        def build_plan(self, *args, **kwargs):
            return {"steps": []}

    class Planner:
        def execute(self, _plan):
            return {"observations": [None], "critic": {"accepted": True}, "plan": {}, "rollback": []}

    monkeypatch.setattr(cycle, "build_production_broker", lambda *args, **kwargs: type("Broker", (), {"policies": {"web.search": {}}})())
    monkeypatch.setattr(cycle, "MasterAgent", Master)
    monkeypatch.setattr(cycle, "build_production_planner", lambda *args, **kwargs: Planner())
    monkeypatch.setenv("ATENA_TOOL_AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    result = cycle.run_agent_validation("programação", "analisar código")
    assert result["status"] == "blocked"
    assert result["observations"] == []
    assert "error" not in result
