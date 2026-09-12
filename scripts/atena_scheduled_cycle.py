#!/usr/bin/env python3
"""Executa um ciclo curto e auditável de aprendizagem local da ATENA.

O modelo gera observações e propostas; não recebe permissão para editar código-fonte.
As propostas ficam em atena_evolution/proposals para revisão e testes posteriores.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.episodic_memory import build_episode
from core.memory_store import MemoryStore
from core.memory_consolidation import compact_context
from core.memory_retrieval import format_context, retrieve_context
from core.evolution_quality_gate import evaluate_cycle
from core.learning_progress import LearningProgress
from core.consequence_memory import ConsequenceMemory
from core.autonomous_capability_router import research_for_capability, select_capability
from core.research_sources import fetch_configured_sources
from core.atena_llm_router import AtenaLLMRouterAdvanced
from core.knowledge_base import KnowledgeBase
from core.executors.factory import build_production_broker, build_production_planner
from core.specialized_agents import MasterAgent

MEMORY_PATH = ROOT / "atena_evolution" / "llm_learning_memory.json"
PROPOSALS_DIR = ROOT / "atena_evolution" / "proposals"
SQLITE_PATH = Path(os.getenv("ATENA_MEMORY_DB", str(ROOT / "atena_evolution" / "memory.sqlite3")))
MODEL = os.getenv("ATENA_LOCAL_MODEL", "qwen2.5:3b-instruct")
EVOLUTION_TASK_TYPE = os.getenv("ATENA_EVOLUTION_TASK_TYPE", "github_evolution")
SQLITE_REQUIRED = os.getenv("ATENA_SQLITE_REQUIRED", "0").lower() in {"1", "true", "yes"}
SYSTEM_VERSION = os.getenv("GITHUB_SHA", "local")

RESEARCH_TOPICS = [
    ("matemática", "Provar e calcular a integral imprópria de 0 a infinito de x^3/(e^x - 1) dx, justificando a troca soma-integral, usando zeta de Riemann e fazendo verificação numérica independente."),
    ("memória histórica", "Como recuperar evidências antigas sem confundir hipótese com fato?"),
    ("deduplicação", "Como detectar memórias repetidas e preservar apenas novas evidências?"),
    ("segurança", "Quais riscos operacionais novos devem ser testados no próximo ciclo?"),
    ("qualidade de código", "Qual módulo ou teste pode melhorar a confiabilidade do sistema?"),
    ("fontes externas", "Quais fontes públicas autorizadas podem preencher as lacunas atuais?"),
    ("generalização", "Como testar o mesmo princípio em um domínio inédito?"),
    ("FAISS e recuperação", "Como melhorar a busca semântica e a diversidade do contexto?"),
    ("autocorreção", "Qual falha observada precisa de um teste de regressão novo?"),
]
SOURCE_MODULE_PATH = ROOT / "core" / "Atena sources extended.py"


def load_memory() -> list[dict]:
    if not MEMORY_PATH.exists():
        return []
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
REQUIRED_KEYS = {"insights", "risks", "proposed_changes", "next_cycle"}
MODEL_SCHEMA = {
    "type": "object",
    "required": ["insights", "risks", "proposed_changes", "next_cycle"],
    "properties": {
        "insights": {"type": "array", "items": {"type": "object", "required": ["text", "evidence_refs", "type", "confidence"], "properties": {"text": {"type": "string"}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "type": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "proposed_changes": {"type": "array", "items": {"type": "object"}},
        "next_cycle": {"type": "array", "items": {"type": "string"}},
    },
}


def parse_model_json(raw: str) -> dict:
    """Normalize Ollama output and reject anything outside the expected schema."""
    cleaned = ANSI_RE.sub("", raw).replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("A resposta do modelo não contém um objeto JSON")
    parsed, _ = decoder.raw_decode(cleaned[start:])
    if not isinstance(parsed, dict) or not REQUIRED_KEYS.issubset(parsed):
        raise ValueError("A resposta do modelo não atende ao esquema de evolução")
    if not isinstance(parsed["insights"], list):
        raise ValueError("insights deve ser uma lista")
    normalized_insights = []
    for item in parsed["insights"]:
        # Compatibilidade com memórias antigas; novos retornos devem ser objetos.
        if isinstance(item, str):
            normalized_insights.append({"text": item, "evidence_refs": [], "type": "limitation", "confidence": 0.0})
            continue
        if not isinstance(item, dict) or not {"text", "evidence_refs", "type", "confidence"}.issubset(item):
            raise ValueError("cada insight precisa de text, evidence_refs, type e confidence")
        if not isinstance(item["text"], str) or not isinstance(item["evidence_refs"], list) or not all(isinstance(ref, str) for ref in item["evidence_refs"]):
            raise ValueError("text e evidence_refs têm tipos inválidos")
        if not isinstance(item["confidence"], (int, float)) or not 0 <= item["confidence"] <= 1:
            raise ValueError("confidence do insight deve estar entre 0 e 1")
        item["evidence_refs"] = [ref.strip() for ref in item["evidence_refs"] if ref.strip()]
        if not item["evidence_refs"]:
            item["confidence"] = 0.0
            item["type"] = "limitation"
        normalized_insights.append(item)
    parsed["insights"] = normalized_insights
    if not isinstance(parsed["risks"], list) or not all(isinstance(item, str) for item in parsed["risks"]):
        raise ValueError("risks deve ser uma lista de textos")
    if not isinstance(parsed["next_cycle"], list) or not all(isinstance(item, str) for item in parsed["next_cycle"]):
        raise ValueError("next_cycle deve ser uma lista de textos")
    if not isinstance(parsed["proposed_changes"], list):
        raise ValueError("proposed_changes deve ser uma lista")
    valid_changes = []
    rejected_changes = 0
    for proposal in parsed["proposed_changes"]:
        if not isinstance(proposal, dict) or not {"file", "rationale", "tests"}.issubset(proposal):
            rejected_changes += 1
            continue
        if not isinstance(proposal["file"], str) or not isinstance(proposal["rationale"], str):
            rejected_changes += 1
            continue
        if not isinstance(proposal["tests"], list) or not all(isinstance(item, str) for item in proposal["tests"]):
            rejected_changes += 1
            continue
        valid_changes.append(proposal)
    if rejected_changes:
        parsed["risks"].append(
            f"{rejected_changes} proposta(s) do modelo foram descartadas por não atenderem ao contrato file/rationale/tests."
        )
        parsed["next_cycle"].append(
            "Reformular propostas de alteração no schema obrigatório antes de qualquer Pull Request."
        )
    parsed["proposed_changes"] = valid_changes
    return parsed


def cycle_to_episode(cycle: dict) -> dict:
    """Converte o ciclo e seu trace agentivo para o contrato episódico."""
    observations = cycle["observations"]
    output = json.dumps(
        {
            "observations": observations,
            "agent_trace": cycle.get("agent_trace"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return build_episode(
        record_type="outcome",
        task_id="scheduled-learning-cycle",
        domain="self_evolution",
        output=output,
        source_type="llm",
        source_id=f"cycle:{cycle['timestamp']}",
        system_version=SYSTEM_VERSION,
        model=cycle.get("model", MODEL),
        status="unverified",
        confidence=0.0,
        event_extra={
            "environment": {
                "duration_limit_seconds": cycle.get("duration_limit_seconds", 300),
                "storage_mode": "dual-write",
            }
        },
    )


def write_sqlite_cycle(cycle: dict) -> str:
    """Persiste o ciclo no SQLite e verifica a integridade da cadeia."""
    episode = cycle_to_episode(cycle)
    with MemoryStore(SQLITE_PATH) as store:
        memory_id = store.append(episode)
        store.verify_integrity()
    return memory_id


def link_cycle_evidence(cycle_id: str, observations: dict, source_ids: set[str]) -> str:
    """Liga evidence_refs válidos ao episódio do ciclo e promove conservadoramente."""
    refs: set[str] = set()
    for insight in observations.get("insights", []):
        if isinstance(insight, dict):
            refs.update(str(ref) for ref in insight.get("evidence_refs", []) if str(ref) in source_ids)
    with MemoryStore(SQLITE_PATH) as store:
        for ref in sorted(refs):
            store.link_evidence(cycle_id, ref, "supports", weight=0.7)
        return store.promote_from_evidence(cycle_id, min_sources=2, confirm_sources=3)


def choose_research_topic(memory: list[dict]) -> tuple[str, str]:
    previous = [item.get("research", {}).get("topic") for item in memory if isinstance(item, dict)]
    for topic, question in RESEARCH_TOPICS:
        if topic not in previous[-len(RESEARCH_TOPICS):]:
            return topic, question
    index = len(memory) % len(RESEARCH_TOPICS)
    return RESEARCH_TOPICS[index]


def collect_research(topic: str, question: str, mode: str = "autonomous") -> dict:
    """Coleta evidências; fontes estendidas só são usadas em consultas explícitas."""
    if mode not in {"autonomous", "interactive"}:
        raise ValueError(f"modo de pesquisa inválido: {mode}")
    query = f"ATENA {topic}: {question}"
    result = {"topic": topic, "question": question, "query": query, "mode": mode, "sources": [], "rss_sources": [], "errors": []}
    try:
        result["rss_sources"] = fetch_configured_sources(query, max_sources=4, limit_per_source=5, mode=mode)
    except Exception as exc:
        result["errors"].append(f"RSS {type(exc).__name__}: {exc}")
    # O catálogo estendido não possui o mesmo contrato de modo; por isso,
    # ele nunca é chamado durante a rotação autônoma.
    if mode != "interactive":
        return result
    if not SOURCE_MODULE_PATH.exists():
        result["errors"].append("módulo de fontes ausente")
        return result
    try:
        spec = importlib.util.spec_from_file_location("atena_sources_extended_runtime", SOURCE_MODULE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("não foi possível carregar o módulo de fontes")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        fetched = module.fetch_all_relevant(query, max_sources=4, timeout_per=6)
        for item in fetched:
            details = json.dumps(item.details, ensure_ascii=False, sort_keys=True)
            result["sources"].append({
                "source": item.source,
                "category": item.category,
                "ok": bool(item.ok),
                "details": details[:1200],
            })
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result


def persist_research_sources(research: dict) -> list[str]:
    """Grava fontes bem-sucedidas como episódios independentes e injeta seus IDs."""
    persisted: list[str] = []
    with MemoryStore(SQLITE_PATH) as store:
        for source in research.get("sources", []):
            if not isinstance(source, dict) or not source.get("ok"):
                continue
            source_name = str(source.get("source", "external"))
            output = str(source.get("details", ""))[:4000]
            if not output:
                continue
            episode = build_episode(
                record_type="observation", task_id=f"research:{research.get('topic', 'unknown')}",
                domain=str(source.get("category", "external_research")), output=output,
                source_type="external_source", source_id=f"source:{source_name}",
                source_url=source.get("source_url") or source.get("url"), system_version=SYSTEM_VERSION,
                status="unverified", confidence=0.0,
            )
            ref = store.append(episode)
            source["evidence_ref"] = ref
            persisted.append(ref)
        for feed in research.get("rss_sources", []):
            if not isinstance(feed, dict) or not feed.get("ok"):
                continue
            for item in feed.get("items", []):
                if not isinstance(item, dict):
                    continue
                output = json.dumps({"title": item.get("title"), "summary": item.get("summary"), "published_at": item.get("published_at"), "link": item.get("link")}, ensure_ascii=False, sort_keys=True)
                episode = build_episode(
                    record_type="observation", task_id=f"research:{research.get('topic', 'unknown')}",
                    domain=str(item.get("category", feed.get("category", "rss"))), output=output[:4000],
                    source_type="external_source", source_id=f"rss:{item.get('content_hash') or item.get('link') or feed.get('source')}",
                    source_url=item.get("link") or item.get("source_url"), system_version=SYSTEM_VERSION,
                    status="unverified", confidence=0.0,
                )
                ref = store.append(episode)
                item["evidence_ref"] = ref
                persisted.append(ref)
        store.verify_integrity()
    return persisted


def content_fingerprint(observations: dict) -> str:
    compact = {
        "insights": observations.get("insights", []),
        "risks": observations.get("risks", []),
        "proposed_changes": observations.get("proposed_changes", []),
        "next_cycle": observations.get("next_cycle", []),
    }
    return hashlib.sha256(json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def insight_text(item: object) -> str:
    return str(item.get("text", "")) if isinstance(item, dict) else str(item)


def build_evidence_fallback(research: dict) -> dict | None:
    """Registra a absorção de duas fontes novas sem inventar uma conclusão factual."""
    refs: list[str] = []
    titles: list[str] = []
    for feed in research.get("rss_sources", []):
        items = feed.get("items", []) if isinstance(feed, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("evidence_ref", "")).strip()
            if not ref or ref in refs:
                continue
            refs.append(ref)
            titles.append(str(item.get("title") or item.get("source") or "fonte pública").strip())
            if len(refs) >= 2:
                break
        if len(refs) >= 2:
            break
    if len(refs) < 2:
        return None
    return {
        "text": (
            f"Foram absorvidas duas evidências públicas novas sobre {research.get('topic', 'o tema')}: "
            f"{titles[0]} e {titles[1]}. Elas ainda precisam ser comparadas antes de confirmar uma conclusão factual."
        ),
        "evidence_refs": refs,
        "type": "observation",
        "confidence": 0.5,
    }


def deduplicate_observations(observations: dict, memory: list[dict]) -> dict:
    """Remove repetições literais preservando referências epistemológicas."""
    old_items = []
    old_files = set()
    for cycle in memory[-20:]:
        old = cycle.get("observations", {}) if isinstance(cycle, dict) else {}
        old_items.extend(insight_text(item) for item in old.get("insights", []))
        old_items.extend(old.get("risks", []))
        old_items.extend(old.get("next_cycle", []))
        for change in old.get("proposed_changes", []):
            if isinstance(change, dict) and change.get("file"):
                old_files.add(str(change["file"]).strip().lower())
    old_normalized = {" ".join(str(x).lower().split()) for x in old_items}
    for key in ("insights", "risks", "next_cycle"):
        unique = []
        seen = set()
        for item in observations.get(key, []):
            text = insight_text(item)
            normalized = " ".join(text.lower().split())
            if normalized and normalized not in seen and normalized not in old_normalized:
                unique.append(item)
                seen.add(normalized)
        observations[key] = unique
    unique_changes = []
    seen_files = set()
    for change in observations.get("proposed_changes", []):
        if not isinstance(change, dict):
            continue
        filename = str(change.get("file", "")).strip()
        normalized_file = filename.lower()
        if filename and normalized_file not in old_files and normalized_file not in seen_files:
            unique_changes.append(change)
            seen_files.add(normalized_file)
    observations["proposed_changes"] = unique_changes
    return observations


def ask_local_model(memory: list[dict], research: dict, topic: str, question: str, sqlite_context: str = "", lesson_context: str = "", agent_context: str = "") -> tuple[dict, str, str]:
    context = json.dumps(compact_context(memory[-200:], max_items=30), ensure_ascii=False, indent=2)[:9000]
    research_context = json.dumps(research, ensure_ascii=False, indent=2)[:7000]
    sqlite_context = sqlite_context or "(nenhum contexto SQLite recuperado)"
    lesson_context = lesson_context or "(nenhuma lição validada recuperada)"
    agent_context = agent_context or "(nenhuma validação agentiva disponível)"
    prompt = f"""Você é o módulo local de análise da ATENA. Faça um ciclo de aprendizagem de no máximo cinco minutos.
Responda SOMENTE com um objeto JSON, sem Markdown, sem comentários, sem códigos ANSI e sem texto antes ou depois.
As chaves obrigatórias são: insights (lista de objetos), risks (lista de strings), proposed_changes
(lista de objetos com file, rationale e tests) e next_cycle (lista de strings). Cada insight DEVE ter exatamente
text (texto), evidence_refs (lista de IDs ou source_ids usados), type (fact, hypothesis, observation ou limitation)
e confidence (número entre 0 e 1). Não escreva código, não peça segredos e não recomende alterações fora de
atena_evolution/proposals. Diferencie fatos de hipóteses.

REGRAS DE DIVERSIDADE:
- Não repita literalmente insights, riscos, propostas ou próximos passos presentes na memória.
- Se a memória for insuficiente, declare essa lacuna, mas formule uma pergunta inédita e verificável.
- Analise o tema deste ciclo: {topic}.
- Responda como a pesquisa deve continuar no próximo ciclo, incluindo fontes, pergunta, evidência esperada e teste de confirmação.
- Não trate resultado de uma única fonte como fato confirmado.
- Toda afirmação factual deve citar pelo menos um evidence_ref existente nos dados coletados ou na memória SQLite.
- Se existirem pelo menos duas evidências novas com evidence_ref, gere ao menos uma observação ou hipótese citando esses refs.
- Se não houver evidência suficiente, use type=limitation ou type=hypothesis, evidence_refs=[], confidence=0.0 e explique a lacuna.
- Nunca invente IDs, URLs ou fontes; referências ausentes invalidam a promoção.

Pergunta de investigação: {question}
Dados coletados das fontes públicas autorizadas:
{research_context}
Memória recente legada:
{context}

Memória episódica SQLite recuperada por relevância:
{sqlite_context}

Lições validadas recuperadas antes deste ciclo:
{lesson_context}
Use-as somente quando forem aplicáveis; registre uma nova evidência antes de tratá-las como confirmação atual.

Trace da validação PlannerExecutorCritic:
{agent_context}
    """
    async def generate_with_router() -> object:
        router = AtenaLLMRouterAdvanced()
        return await router.generate(
            prompt,
            task_type=EVOLUTION_TASK_TYPE,
            temperature=0.1,
            max_tokens=1500,
        )

    try:
        response = asyncio.run(generate_with_router())
        return parse_model_json(response.content), response.provider, response.model
    except Exception as router_exc:
        # Compatibilidade operacional: se o roteador não puder ser inicializado,
        # tenta primeiro o proxy OpenAI configurado e depois o endpoint local.
        print(f"roteador multi-API indisponível; tentando fallback OpenAI/Ollama: {type(router_exc).__name__}", file=sys.stderr)

    # O ciclo não deve falhar apenas porque Ollama não está instalado ou
    # iniciado. O proxy OpenAI é o fallback operacional já usado pela CI;
    # a saída continua sujeita ao mesmo parse_model_json e aos mesmos gates.
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            model = os.getenv("ATENA_CYCLE_OPENAI_MODEL", "gpt-5-mini")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=1800,
                extra_body={"reasoning": {"effort": os.getenv("ATENA_CYCLE_REASONING", "minimal")}},
            )
            content = response.choices[0].message.content or ""
            return parse_model_json(content), "openai", model
        except Exception as openai_exc:
            print(f"fallback OpenAI indisponível: {type(openai_exc).__name__}", file=sys.stderr)

    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": MODEL_SCHEMA,
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama indisponível em {host}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama retornou uma resposta HTTP que não é JSON") from exc
    content = body.get("message", {}).get("content")
    if not isinstance(content, str):
        raise RuntimeError("Resposta do Ollama não contém message.content textual")
    return parse_model_json(content), "local", MODEL


def run_agent_validation(topic: str, question: str) -> dict:
    """Executa validações read-only antes do modelo e retorna o trace auditável."""
    audit_path = Path(os.getenv("ATENA_TOOL_AUDIT_PATH", str(ROOT / "atena_evolution" / "tool_audit.jsonl")))
    sources_config = Path(os.getenv("ATENA_RESEARCH_SOURCES_CONFIG", str(ROOT / "config" / "research_sources.json")))
    sandbox_workspace = os.getenv("ATENA_SANDBOX_WORKSPACE", "").strip()
    try:
        broker = build_production_broker(
            SQLITE_PATH,
            audit_path=audit_path,
            sources_config=sources_config,
            workspace=Path(sandbox_workspace) if sandbox_workspace else None,
        )
        master = MasterAgent()
        agent = master.assign(f"{topic}: {question}")
        planner = build_production_planner(broker, allowed_tools=agent.blueprint.allowed_tools)
        plan = master.build_plan(
            agent,
            topic=topic,
            question=question,
            available_tools=tuple(
                tool_name
                for tool_name in agent.blueprint.allowed_tools
                if tool_name in broker.policies
            ),
        )
        result = planner.execute(plan)
        web_observation = next(
            (
                item for item in result["observations"]
                if item.get("output", {}).get("tool_result", {}).get("name") == "web.search"
            ),
            None,
        )
        web_output = web_observation.get("output", {}) if web_observation else {}
        if result["critic"]["accepted"] and not web_output.get("items"):
            result["critic"]["accepted"] = False
            result["critic"]["missing_evidence"] = [*result["critic"].get("missing_evidence", []), "web"]
            result["critic"]["explanation"] = "pesquisa web executada, mas não retornou evidência de fonte"
        return {
            "status": "accepted" if result["critic"]["accepted"] else "blocked",
            "agent": agent.describe(),
            "plan": result["plan"],
            "observations": result["observations"],
            "rollback": result["rollback"],
            "critic": result["critic"],
            "audit_path": str(audit_path),
        }
    except Exception as exc:
        return {
            "status": "error",
            "agent": None,
            "plan": None,
            "observations": [],
            "rollback": [],
            "critic": {"accepted": False, "failed_steps": [], "missing_evidence": [], "rollback_failures": [], "explanation": "validação agentiva falhou"},
            "error": f"{type(exc).__name__}: {exc}",
            "audit_path": str(audit_path),
        }


def main() -> int:
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    if os.getenv("ATENA_SANDBOX_MODE", "process").strip().lower() == "container":
        workspace = os.getenv("ATENA_SANDBOX_WORKSPACE", "").strip()
        if not workspace:
            print("sandbox container exige ATENA_SANDBOX_WORKSPACE", file=sys.stderr)
            return 1
        healthcheck = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "rootless_sandbox_healthcheck.py"),
                "--workspace", workspace,
                "--image", os.getenv("ATENA_SANDBOX_IMAGE", "atena-sandbox-test:latest"),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if healthcheck.returncode != 0:
            print("healthcheck rootless falhou; ciclo abortado", file=sys.stderr)
            print(healthcheck.stderr or healthcheck.stdout[-2000:], file=sys.stderr)
            return 1
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    memory = load_memory()
    intent = None
    try:
        with MemoryStore(SQLITE_PATH) as store:
            intent = store.claim_next_research()
    except Exception as exc:
        print(f"fila de pesquisa indisponível: {exc}", file=sys.stderr)
    if intent:
        topic = str(intent["topic"])
        question = str(intent.get("question") or f"Pesquisar fontes e evidências sobre {topic}.")
    elif os.getenv("ATENA_RESEARCH_TOPIC", "").strip() or os.getenv("ATENA_RESEARCH_QUESTION", "").strip():
        topic = os.getenv("ATENA_RESEARCH_TOPIC", "geral").strip() or "geral"
        question = os.getenv("ATENA_RESEARCH_QUESTION", "").strip() or f"Pesquisar fontes e evidências sobre {topic}."
    else:
        topic, question = choose_research_topic(memory)
    research_mode = "interactive" if intent else "autonomous"
    capability = select_capability(topic, question)
    research = research_for_capability(topic, question, mode=research_mode)
    if research is None:
        research = collect_research(topic, question, mode=research_mode)
    research.setdefault("capability", {
        "name": capability.name,
        "tools": list(capability.tools),
        "reason": capability.reason,
        "confidence": capability.confidence,
    })
    research["requested_by"] = "telegram" if intent else "rotation"
    research["intent_id"] = intent.get("id") if intent else None
    research["mode"] = research_mode
    source_episode_ids: set[str] = set()
    try:
        source_episode_ids = set(persist_research_sources(research))
    except Exception as exc:
        print(f"persistência de fontes falhou: {exc}", file=sys.stderr)
    sqlite_context = ""
    try:
        sqlite_context = format_context(retrieve_context(SQLITE_PATH, f"{topic} {question}", limit=12))
        with KnowledgeBase(SQLITE_PATH) as knowledge:
            hits = knowledge.search(f"{topic} {question}", limit=10)
        if hits:
            sqlite_context += "\n\nBase de conhecimento geral (fontes previamente pesquisadas):\n" + json.dumps(hits, ensure_ascii=False, indent=2)[:9000]
    except Exception as exc:
        print(f"recuperação SQLite/base de conhecimento indisponível: {exc}", file=sys.stderr)
    validated_lessons: list[dict] = []
    try:
        with ConsequenceMemory(SQLITE_PATH) as consequence_store:
            validated_lessons = consequence_store.search_validated_lessons(f"{topic} {question}", limit=5)
    except Exception as exc:
        print(f"recuperação de lições validadas indisponível: {exc}", file=sys.stderr)
    lesson_context = json.dumps(validated_lessons, ensure_ascii=False, indent=2)[:6000]
    agent_trace = run_agent_validation(topic, question)
    agent_context = json.dumps(agent_trace, ensure_ascii=False, indent=2)[:10000]
    observations, provider_used, model_used = ask_local_model(memory, research, topic, question, sqlite_context, lesson_context, agent_context)
    observations = deduplicate_observations(observations, memory)
    if not observations.get("insights"):
        fallback = build_evidence_fallback(research)
        observations["insights"] = [fallback] if fallback else [{
            "text": f"Nenhuma conclusão nova foi confirmada sobre {topic}; a lacuna de evidência será investigada antes de consolidar uma memória.",
            "evidence_refs": [], "type": "limitation", "confidence": 0.0,
        }]
    if not observations.get("next_cycle"):
        observations["next_cycle"] = [
            f"Comparar pelo menos duas evidências independentes sobre {topic} antes de consolidar uma conclusão."
        ]
    quality_gate = evaluate_cycle(observations)
    observations["quality_gate"] = quality_gate.to_dict()
    observations["learning_trace"] = {
        "validated_lessons_consulted": [
            item.get("lesson", {}).get("lesson_id") for item in validated_lessons
            if isinstance(item, dict) and isinstance(item.get("lesson"), dict)
        ],
        "lesson_query": f"{topic} {question}",
        "lesson_use_claim": "consulted_not_proven_applied",
    }
    observations["research_plan"] = {
        "topic": topic,
        "question": question,
        "capability": research.get("capability"),
        "sources_to_consult": [item["source"] for item in research.get("sources", []) if item.get("ok")],
        "evidence_expected": "comparar pelo menos duas evidências independentes antes de consolidar um fato",
        "next_test": f"verificar uma instância inédita relacionada a {topic}",
        "retrieval": {"source": "sqlite", "episode_limit": 12, "context_chars": len(sqlite_context)},
    }
    cycle = {
        "timestamp": now.isoformat(),
        "model": model_used,
        "provider": provider_used,
        "task_type": EVOLUTION_TASK_TYPE,
        "duration_limit_seconds": 300,
        "research": research,
        "capability_learning": {
            "decision": research.get("capability"),
            "specialized_answer_available": bool(research.get("specialized_answer")),
            "specialized_metadata": research.get("specialized_metadata"),
            "evidence_count": len(source_episode_ids),
            "next_cycle_should_reuse": bool(source_episode_ids),
        },
        "agent_trace": agent_trace,
        "observations": observations,
    }
    memory.append(cycle)
    # Compatibilidade: o JSON legado continua sendo escrito primeiro.
    MEMORY_PATH.write_text(json.dumps(memory[-200:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proposal_path = PROPOSALS_DIR / f"cycle-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    proposal_path.write_text(json.dumps(cycle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sqlite_status = "ok"
    progress_status = "ok"
    sqlite_memory_id = None
    promoted_status = "unverified"
    try:
        sqlite_memory_id = write_sqlite_cycle(cycle)
        if sqlite_memory_id and source_episode_ids:
            promoted_status = link_cycle_evidence(sqlite_memory_id, observations, source_episode_ids)
        with LearningProgress(SQLITE_PATH) as progress:
            progress.record_lesson_usage(cycle["timestamp"], f"{topic} {question}", validated_lessons)
            progress.record_cycle(
                cycle_id=cycle["timestamp"], model=model_used,
                evidence_count=len(source_episode_ids),
                validated_lesson_count=len(validated_lessons),
                lessons_consulted_count=len(validated_lessons),
                regression_status="pass" if quality_gate.passed else "blocked",
                payload={"sqlite_memory_id": sqlite_memory_id, "promoted_status": promoted_status},
            )
        if intent:
            with MemoryStore(SQLITE_PATH) as store:
                store.complete_research(intent["id"], cycle["timestamp"], {"topic": topic, "sqlite_memory_id": sqlite_memory_id, "promoted_status": promoted_status, "source_episode_count": len(source_episode_ids), "status": "completed"})
    except Exception as exc:
        sqlite_status = f"error:{type(exc).__name__}"
        progress_status = f"error:{type(exc).__name__}"
        print(f"SQLite dual-write falhou: {exc}", file=sys.stderr)
        if intent:
            try:
                with MemoryStore(SQLITE_PATH) as store:
                    store.complete_research(intent["id"], cycle["timestamp"], {"topic": topic, "error": str(exc)}, failed=True)
            except Exception:
                pass
        if SQLITE_REQUIRED:
            raise

    print(json.dumps({
        "model": model_used,
        "provider": provider_used,
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "memory": str(MEMORY_PATH),
        "proposal": str(proposal_path),
        "sqlite": str(SQLITE_PATH),
        "sqlite_status": sqlite_status,
        "sqlite_memory_id": sqlite_memory_id,
        "source_episode_count": len(source_episode_ids),
        "promoted_status": promoted_status,
        "progress_status": progress_status,
        "validated_lessons_consulted": len(validated_lessons),
        "capability": research.get("capability"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
