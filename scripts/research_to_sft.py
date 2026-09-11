#!/usr/bin/env python3
"""Converte pesquisas verificadas da Atena em experiências e dataset SFT.

Fontes aceitas:
- atena_evolution/learning_memory.jsonl, quando contém resposta/resumo e URLs;
- knowledge_documents/knowledge_research no SQLite, quando há resumo ou texto útil.

O script não baixa páginas nem inventa respostas. Ele só transforma evidência já
persistida, exige URL para pesquisas externas e grava primeiro no ledger idempotente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.autonomous_learning import Experience, ExperienceLedger, build_datasets

EVOLUTION = ROOT / "atena_evolution"
MEMORY_PATH = EVOLUTION / "learning_memory.jsonl"
SQLITE_PATH = EVOLUTION / "memory.sqlite3"


def clean(value: Any, limit: int = 12000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def valid_url(value: Any) -> bool:
    text = clean(value, 2000)
    return text.startswith(("https://", "http://"))


def stable_source(*parts: str) -> str:
    return "research:" + hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def evidence_refs(item: dict[str, Any]) -> list[str]:
    candidates = item.get("evidence_refs") or item.get("sources") or item.get("source_urls") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    refs = [clean(value, 2000) for value in candidates if valid_url(value)]
    source_url = item.get("source_url") or item.get("url")
    if valid_url(source_url):
        refs.append(clean(source_url, 2000))
    return list(dict.fromkeys(refs))[:8]


def append_research_item(ledger: ExperienceLedger, *, topic: str, response: str, refs: list[str], source: str, score: float = 0.75) -> bool:
    topic = clean(topic, 1000)
    response = clean(response, 12000)
    if not topic or len(response) < 80 or not refs:
        return False
    prompt = (
        "Explique de forma clara, verificável e atualizada o que as fontes indicam sobre: "
        f"{topic}. Cite as limitações e a data/jurisdição quando forem relevantes."
    )
    return ledger.append(Experience(
        prompt=prompt,
        response=response,
        score=max(0.65, min(1.0, score)),
        source=source,
        topic=topic,
        evidence=refs,
    ))


def collect_learning_memory(ledger: ExperienceLedger) -> int:
    if not MEMORY_PATH.exists():
        return 0
    created = 0
    for line in MEMORY_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        response = next((payload.get(key) for key in ("full_text", "answer", "response", "summary", "analysis", "memory") if isinstance(payload.get(key), str)), "")
        refs = evidence_refs({**item, **payload})
        if append_research_item(ledger, topic=item.get("topic") or payload.get("topic", ""), response=response, refs=refs, source="internet_learning_memory"):
            created += 1
    return created


def collect_sqlite(ledger: ExperienceLedger) -> int:
    if not SQLITE_PATH.exists():
        return 0
    created = 0
    con = sqlite3.connect(SQLITE_PATH)
    try:
        rows = con.execute("SELECT url, title, domain, topic, fetched_at, metadata_json, content FROM knowledge_documents").fetchall()
        for url, title, domain, topic, fetched_at, metadata_raw, content in rows:
            try:
                metadata = json.loads(metadata_raw or "{}")
            except json.JSONDecodeError:
                metadata = {}
            response = metadata.get("summary") or metadata.get("answer") or metadata.get("abstract")
            # Conteúdo bruto só é aceito quando o pipeline marcou-o como resumo.
            if not response and metadata.get("is_summary") is True:
                response = content
            if append_research_item(
                ledger,
                topic=topic or title or domain,
                response=response or "",
                refs=[url] if valid_url(url) else [],
                source="sqlite_research",
                score=float(metadata.get("quality_score", 0.75) or 0.75),
            ):
                created += 1
    finally:
        con.close()
    return created


SEED_EXAMPLES = [
    ("direito constitucional", "Explique como analisar uma questão constitucional sem substituir a consulta à Constituição, à legislação regulamentadora e à jurisprudência atual.", "A análise deve identificar o dispositivo constitucional, a legislação relacionada, os fatos relevantes, a jurisprudência aplicável e a data das fontes. Uma resposta geral não constitui parecer jurídico nem substitui a atuação de profissional habilitado."),
    ("direito civil", "Explique a diferença geral entre responsabilidade civil contratual e extracontratual no Brasil.", "A responsabilidade contratual normalmente decorre do descumprimento de uma obrigação assumida, enquanto a extracontratual decorre da violação de um dever jurídico geral. A classificação e as consequências dependem dos fatos, da legislação vigente e da jurisprudência. A resposta é informativa e não é aconselhamento jurídico."),
    ("direito penal", "Como estudar um tipo penal com segurança e sem transformar uma explicação em aconselhamento para um caso concreto?", "É preciso consultar o texto legal vigente, verificar elementos objetivos e subjetivos, causas de exclusão e entendimentos jurisprudenciais, sempre distinguindo estudo acadêmico de orientação para um caso. Questões concretas exigem advogado ou defensoria e análise integral dos autos."),
    ("direito do trabalho", "Quais cuidados são necessários ao pesquisar direitos trabalhistas na internet?", "Deve-se conferir a Consolidação das Leis do Trabalho, normas regulamentadoras, convenções ou acordos coletivos, decisões recentes e a data da fonte. Regras podem variar conforme categoria, contrato e localidade; uma explicação genérica não substitui consulta profissional."),
    ("direito administrativo", "Como avaliar uma informação sobre licitação e contratação pública?", "A pesquisa deve identificar o ente público, o regime jurídico, a modalidade, o edital, a legislação aplicável e decisões dos órgãos de controle. É importante verificar a fonte oficial e a data, porque procedimentos e normas podem mudar."),
    ("direito e proteção de dados", "Como explicar proteção de dados pessoais sem prometer conformidade jurídica automática?", "A análise deve mapear dados, finalidade, base legal, retenção, segurança, direitos dos titulares e responsabilidades. A legislação e orientações oficiais devem ser consultadas na versão vigente; conformidade depende do contexto e não pode ser garantida por uma resposta genérica."),
    ("direito do consumidor", "Como orientar uma pesquisa sobre um problema de consumo sem concluir o caso antecipadamente?", "É necessário reunir contrato, comprovantes, comunicações, datas e política aplicável, consultar a legislação e fontes oficiais e separar fatos comprovados de alegações. A solução depende do produto, serviço, prejuízo, prazo e jurisdição."),
    ("direito internacional", "Como pesquisar diferenças entre sistemas jurídicos de países diferentes?", "Deve-se declarar a jurisdição, a data e a fonte oficial, evitar transportar conceitos de um país para outro e consultar regras de conflito, tratados e legislação local. Comparações informativas não substituem aconselhamento de profissional habilitado no país relevante."),
    ("programação", "Como diagnosticar um erro de software de forma reproduzível?", "Descreva o ambiente, versão, passos mínimos, entrada, saída esperada e saída observada. Depois isole uma hipótese, crie um teste de regressão, aplique a menor correção e execute os testes relevantes. Registre a mudança e seus limites."),
    ("ciência", "Como distinguir uma hipótese científica de uma afirmação comprovada?", "Uma hipótese é uma explicação testável. Uma afirmação mais forte exige evidências replicáveis, métodos claros, comparação com alternativas e avaliação das limitações. A força da conclusão deve ser proporcional à qualidade e ao volume das evidências."),
    ("cibersegurança", "Quais são os princípios básicos para reduzir risco em uma aplicação web?", "Use autenticação forte, menor privilégio, validação de entrada, proteção de segredos, atualização de dependências, logs sem dados sensíveis, backups testados e revisão de ameaças. Segurança é processo contínuo e deve respeitar autorização para qualquer teste."),
    ("educação", "Como transformar uma pergunta ampla em um plano de estudo verificável?", "Defina objetivo observável, conhecimentos prévios, fontes confiáveis, pequenas atividades, critérios de sucesso e revisão espaçada. Compare o que foi aprendido com exercícios ou explicações próprias, corrigindo erros com fontes adequadas."),
    ("história", "Como pesquisar um acontecimento histórico evitando anacronismos?", "Consulte fontes primárias e secundárias contextualizadas, identifique autoria, data, finalidade e lacunas, compare interpretações e evite aplicar categorias atuais sem explicar a diferença histórica. Incertezas devem ser explicitadas."),
    ("finanças", "Como analisar uma informação financeira sem transformá-la em recomendação de investimento?", "Verifique a fonte, a data, o instrumento, riscos, custos, liquidez e cenários. Diferencie fatos de projeções e considere o perfil do investidor. Uma explicação geral não substitui análise profissional nem garantia de retorno."),
    ("medicina", "Como usar informação médica na internet com responsabilidade?", "Prefira órgãos de saúde e literatura científica, confira data e qualidade da evidência e não trate conteúdo geral como diagnóstico. Sintomas, urgências, medicamentos e decisões clínicas devem ser avaliados por profissional de saúde."),
    ("ética e IA", "Quais controles ajudam a usar uma IA de forma responsável em áreas de alto impacto?", "Use supervisão humana, fontes rastreáveis, avaliação de vieses, proteção de dados, testes de segurança, registro de decisões e canal de contestação. A IA deve indicar incertezas e não assumir autoridade profissional ou institucional que não possui."),
]


def seed_examples(ledger: ExperienceLedger) -> int:
    created = 0
    for index, (topic, prompt, response) in enumerate(SEED_EXAMPLES, 1):
        refs = [f"curated://seed/{index}"]
        if ledger.append(Experience(prompt=prompt, response=response, score=0.9, source="curated_seed", topic=topic, evidence=refs)):
            created += 1
    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Adicionar 16 exemplos iniciais curados")
    parser.add_argument("--no-research", action="store_true", help="Não ler pesquisas persistidas")
    args = parser.parse_args()
    ledger = ExperienceLedger()
    counts = {"seed": seed_examples(ledger) if args.seed else 0}
    counts["learning_memory"] = 0 if args.no_research else collect_learning_memory(ledger)
    counts["sqlite_research"] = 0 if args.no_research else collect_sqlite(ledger)
    datasets = build_datasets(ledger)
    result = {"status": "ok", "created": counts, "datasets": datasets, "sft_path": str(EVOLUTION / "training" / "sft.jsonl")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
