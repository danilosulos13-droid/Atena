from core.research_agent import infer_topic, plan_research

def test_research_plan_is_domain_aware():
    plan = plan_research("qual é a lei sobre responsabilidade civil", "direito")
    assert plan.topic == "direito"
    assert any("legislação" in q for q in plan.subqueries)

def test_research_plan_deduplicates_queries():
    plan = plan_research("o que é Python", "tecnologia")
    assert len(plan.subqueries) == len(set(plan.subqueries))
