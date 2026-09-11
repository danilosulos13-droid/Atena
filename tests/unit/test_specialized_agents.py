import pytest

from core.executors.factory import build_production_broker, build_production_planner
from core.specialized_agents import AgentRegistry, MasterAgent


def test_master_routes_finance_to_analysis_only_agent():
    master = MasterAgent()
    result = master.route("Analisar risco de investimento e cenário de mercado")
    assert result["agent"]["domain"] == "finance"
    assert result["agent"]["name"] == "finance-analyst"
    assert "memory.search" in result["agent"]["allowed_tools"]
    assert result["external_side_effects"] is False
    assert any("Não executar ordens" in item for item in result["agent"]["system_constraints"])


def test_master_routes_programming_to_sandbox_tools():
    master = MasterAgent()
    agent = master.assign("Corrigir bug Python e executar testes")
    assert agent.blueprint.domain == "programming"
    assert "code.run_tests" in agent.blueprint.allowed_tools
    assert agent.blueprint.risk == "sandbox_compute"


def test_master_rejects_unknown_domain_and_active_limit():
    registry = AgentRegistry()
    master = MasterAgent(registry, max_active_agents=1)
    with pytest.raises(ValueError):
        master.create_agent("unknown")  # type: ignore[arg-type]
    master.create_agent("research")
    with pytest.raises(RuntimeError, match="limite"):
        master.create_agent("general")


def test_registry_rejects_duplicate_blueprints():
    from core.specialized_agents import AgentBlueprint
    with pytest.raises(ValueError, match="duplicados"):
        AgentRegistry((
            AgentBlueprint("a", "research", "a", ("memory.search",)),
            AgentBlueprint("b", "research", "b", ("memory.search",)),
        ))


def test_production_planner_exposes_only_selected_agent_tools(tmp_path):
    broker = build_production_broker(tmp_path / "memory.sqlite3")
    planner = build_production_planner(
        broker,
        allowed_tools=("memory.search", "code.run_tests"),
    )
    assert planner.registry.names() == ("code_run_tests", "memory_search")


def test_production_planner_rejects_agent_without_available_tools(tmp_path):
    broker = build_production_broker(tmp_path / "memory.sqlite3")
    with pytest.raises(ValueError, match="não possui ferramentas"):
        build_production_planner(broker, allowed_tools=("github.push",))


def test_finance_custom_plan_has_no_write_or_code_step():
    master = MasterAgent()
    agent = master.assign("Analisar risco financeiro")
    plan = master.build_plan(
        agent,
        topic="mercado",
        question="comparar cenários",
        available_tools=agent.blueprint.allowed_tools,
    )
    assert agent.blueprint.plan_builder == "finance"
    assert [step.tool for step in plan.steps] == ["memory_search", "web_search"]
    assert all(step.requires_approval is False for step in plan.steps)


def test_programming_custom_plan_includes_sandbox_tests():
    master = MasterAgent()
    agent = master.assign("Corrigir bug de programação")
    plan = master.build_plan(
        agent,
        topic="bug Python",
        question="como corrigir?",
        available_tools=agent.blueprint.allowed_tools,
    )
    assert agent.blueprint.plan_builder == "programming"
    assert [step.tool for step in plan.steps] == ["memory_search", "web_search", "code_run_tests"]
    assert plan.steps[-1].parameters["target"] == "tests/unit"
