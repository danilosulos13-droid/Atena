"""Agente de pesquisa aberta, orientado a evidências e domínio.

Pipeline: decomposição -> busca paralela -> diversificação -> pontuação de fontes ->
armazenamento/proveniência -> detecção de conflitos -> síntese estruturada.
Não treina nem altera o modelo automaticamente; produz evidência auditável.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from core.knowledge_base import KnowledgeBase
from core.web_research import WebEvidence, search_web

PRIMARY_HINTS = {
    "direito": ("gov.br", "planalto.gov.br", "stf.jus.br", "stj.jus.br", "trf", "tst.jus.br", "cnj.jus.br"),
    "saude": ("gov.br", "who.int", "paho.org", "nih.gov", "pubmed.ncbi.nlm.nih.gov"),
    "ciência": ("nature.com", "science.org", "nih.gov", "pubmed.ncbi.nlm.nih.gov", "arxiv.org"),
    "nanorobótica": ("pubmed.ncbi.nlm.nih.gov", "europepmc.org", "nih.gov", "ncbi.nlm.nih.gov", "arxiv.org", "nature.com", "ieeexplore.ieee.org"),
    "finanças": ("bcb.gov.br", "gov.br", "cvm.gov.br", "sec.gov"),
    "tecnologia": ("docs.python.org", "developer.mozilla.org", "ietf.org", "w3.org"),
}

@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    snippet: str
    domain: str
    score: float
    primary: bool

@dataclass(frozen=True)
class ResearchPlan:
    question: str
    topic: str
    subqueries: list[str]


def infer_topic(question: str) -> str:
    q = question.casefold()
    for topic, terms in {
        "direito": ("lei", "juríd", "processo", "crime", "constitucional", "contrato"),
        "saude": ("saúde", "doença", "medicamento", "sintoma", "medicina"),
        "nanorobótica": ("nanorrobô", "nanorrobótica", "nanorobot", "nanorobotics", "microrrobô", "microrobotics", "nanomedicina"),
        "finanças": ("investimento", "ações", "juros", "inflação", "financeiro"),
        "ciência": ("pesquisa", "científico", "física", "química", "biologia"),
        "tecnologia": ("python", "software", "ia", "inteligência artificial", "computação"),
    }.items():
        if any(t in q for t in terms):
            return topic
    return "geral"


def plan_research(question: str, topic: str | None = None) -> ResearchPlan:
    topic = topic or infer_topic(question)
    base = " ".join(question.split())[:280]
    queries = [base]
    queries.append(f"{base} fonte primária oficial")
    queries.append(f"{base} evidência estudos dados")
    if topic == "direito":
        queries.extend([f"{base} legislação atualizada", f"{base} jurisprudência STF STJ"])
    elif topic == "saude":
        queries.append(f"{base} guideline revisão sistemática")
    return ResearchPlan(question=base, topic=topic, subqueries=list(dict.fromkeys(queries))[:6])


def _score(item: WebEvidence, topic: str) -> ResearchSource:
    domain = urlparse(item.url).netloc.lower().split(":", 1)[0]
    hints = PRIMARY_HINTS.get(topic, ())
    primary = any(domain == h or domain.endswith("." + h) or h in domain for h in hints)
    score = 0.45 if item.snippet else 0.25
    score += 0.35 if primary else 0.0
    score += 0.10 if domain.endswith((".gov.br", ".gov", ".edu", ".edu.br")) else 0.0
    score += min(len(item.snippet), 500) / 5000
    return ResearchSource(item.title, item.url, item.snippet, domain, round(min(score, 1.0), 4), primary)


def run_research(question: str, topic: str | None = None, *, kb: KnowledgeBase | None = None, limit_per_query: int = 5) -> dict:
    plan = plan_research(question, topic)
    started = datetime.now(timezone.utc).isoformat()
    sources: dict[str, ResearchSource] = {}
    for query in plan.subqueries:
        for item in search_web(query, limit=limit_per_query):
            scored = _score(item, plan.topic)
            sources[scored.url] = scored
    ranked = sorted(sources.values(), key=lambda x: (-x.score, x.domain, x.title))
    # Diversificação: não deixa um único domínio dominar a síntese.
    selected: list[ResearchSource] = []
    domain_counts: dict[str, int] = {}
    for source in ranked:
        if domain_counts.get(source.domain, 0) >= 3:
            continue
        selected.append(source)
        domain_counts[source.domain] = domain_counts.get(source.domain, 0) + 1
        if len(selected) >= 15:
            break
    conflicts = _detect_conflicts(selected)
    if kb:
        for source in selected:
            kb.add_document(url=source.url, title=source.title, topic=plan.topic, content=source.snippet, metadata={"research_question": plan.question, "source_score": source.score, "primary_source": source.primary})
        kb.record_research(query=plan.question, topic=plan.topic, started_at=started, source_count=len(selected), document_count=len(selected), chunk_count=len(selected), status="ok" if selected else "no_sources", summary=_summary(selected, conflicts))
    return {"plan": asdict(plan), "sources": [asdict(s) for s in selected], "conflicts": conflicts, "summary": _summary(selected, conflicts), "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat()}


def _detect_conflicts(sources: list[ResearchSource]) -> list[dict]:
    # Heurística conservadora: só sinaliza possíveis conflitos sem declarar qual fonte está certa.
    groups: dict[str, list[ResearchSource]] = {}
    for s in sources:
        key = re.sub(r"\W+", " ", s.title.casefold()).strip()
        words = " ".join(key.split()[:8])
        if words:
            groups.setdefault(words, []).append(s)
    return [{"topic_key": key, "sources": [s.url for s in vals], "status": "review_required"} for key, vals in groups.items() if len(vals) > 1][:10]


def _summary(sources: list[ResearchSource], conflicts: list[dict]) -> str:
    if not sources:
        return "Nenhuma fonte foi recuperada; não há base suficiente para uma conclusão factual atual."
    primary = sum(1 for s in sources if s.primary)
    text = f"{len(sources)} fontes recuperadas; {primary} aparentam ser fontes primárias/oficiais."
    if conflicts:
        text += f" Há {len(conflicts)} agrupamentos que exigem verificação de possível conflito."
    return text
