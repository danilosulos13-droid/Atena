# Auditoria técnica completa da Atena

> Relatório gerado a partir de auditorias independentes de arquitetura, memória, segurança, workflows e qualidade.

**Escopo:** repositório `/home/ubuntu/Atena-IA`. A análise é predominantemente estática, complementada por testes de componentes quando disponíveis.

# Auditoria consolidada do repositório Atena

## Veredicto executivo

Atena possui bons controles locais: allowlist de ferramentas, contratos Pydantic com `extra=forbid`, validação de argumentos, envelopes `ToolResult`, WAL e `synchronous=FULL` no SQLite, hashes e proveniência em partes da memória, circuit breaker/quota/cache no roteador LLM, hardening em algumas unidades systemd e testes unitários úteis. Esses controles, porém, não formam ainda uma fronteira operacional única.

O principal problema é a divergência entre a arquitetura declarada e os caminhos efetivamente executáveis. O caminho agendado observado é:

```text
GitHub Actions (.github/workflows/atena-ci-and-update.yml, a cada 30 min)
  -> scripts/atena_scheduled_cycle.py
  -> build_production_broker / build_production_planner
  -> core.agent_plan_loop.PlannerExecutorCritic
  -> memory.search + web.search, somente leitura
  -> AtenaLLMRouterAdvanced, com fallback direto para Ollama
```

Ao redor dele existem outros agentes, schedulers, listeners, workflows e caminhos de escrita que não compartilham necessariamente o mesmo broker, aprovação, rastreabilidade, lease ou idempotência. Portanto, a recomendação de auditoria é **não habilitar efeitos externos reais nem tratar o pipeline como release de produção** antes dos controles P0.

As prioridades abaixo são uma classificação consolidada desta auditoria:

- **P0:** contenção imediata; risco crítico, perda/corrupção de dados ou bloqueio de release.
- **P1:** deve ser resolvido antes de ampliar capacidades ou considerar produção confiável.
- **P2:** robustez, mensuração e manutenção importantes, mas não bloqueadoras da contenção inicial.
- **P3:** limpeza, compatibilidade e melhorias de menor urgência.

## Achados consolidados e evidências

### P0 — contenção imediata

| ID | Achado consolidado | Evidência concreta | Ação requerida |
|---|---|---|---|
| P0-1 | **Há risco de injeção de shell em workflow que recebe segredos.** | `.github/workflows/web-research-telegram-smoke.yml:3-10` declara `question` como input de `workflow_dispatch` e o interpola em `run: --question "${{ inputs.question }}"` em `:40-41`; o mesmo job recebe token Telegram, chaves de provedores e `CSE_ID` em `:32-39`. | Remover interpolação direta; passar o valor por `env` e usar aspas sobre variável, limitar tamanho/formato, retirar segredos desnecessários e revisar todos os workflows com `actionlint`/scanner equivalente. |
| P0-2 | **Efeitos externos contornam o ToolBroker, enquanto o envelope do broker pode declarar efeito falso.** | Telegram chama Tasker diretamente em `scripts/atena_telegram_chat.py:542-554,580-602` e Home Assistant em `:566-575`; workflows fazem `git push`, por exemplo `.github/workflows/atena-telegram-listener.yml:98-131` e `x-evolution-proposal.yml:42-61`. Além disso, `core/tool_broker.py:183-193` sempre produz `side_effect=False`, inclusive após executor real. | Bloquear caminhos diretos; encaminhar Tasker, Home Assistant e GitHub por um gateway único; tornar `side_effect` derivado da capability efetiva; exigir chave idempotente, aprovação vinculada ao payload, TTL, auditoria transacional e reconciliação de estado `unknown`. |
| P0-3 | **A autorização Telegram é insuficiente para efeitos sensíveis.** | A autorização principal é por `chat_id` em `scripts/atena_telegram_chat.py:706-713`; a aprovação pendente é um dicionário em memória por chat em `:582-589`, sem evidência de `user_id`, hash do payload, expiração, persistência ou limite de tentativas. `callback_query` é tratado em `:702-705` antes da checagem de allowlist aplicada ao ramo de mensagens. | Negar grupos por padrão, autorizar por usuário e chat, vincular aprovação a `tool_call_id`, ator, argumentos e digest, usar token de uso único com TTL, persistir estados e aplicar a mesma autorização a callbacks. |
| P0-4 | **Coleta web não tem proteção SSRF suficiente e conteúdo não confiável atravessa a fronteira de instruções.** | `core/research_sources.py:73-79,117-121` usa `urllib.request.urlopen` com URL configurável, sem evidência de bloqueio de loopback, IP privado, link-local, metadata endpoint ou revalidação de redirects. `core/executors/web.py:53-74` retorna conteúdo de rede como `untrusted_content=True`; `core/web_research.py:196-202` concatena título, URL e trecho no contexto do modelo. | Usar allowlist de host/path, HTTPS, resolução e validação de IP final, bloqueio de redirects perigosos, limites de tempo/bytes e egress controlado; representar conteúdo externo como dados tainted, nunca como instruções; impedir ação e promoção automática de evidência não verificada. |
| P0-5 | **O “sandbox” de auto-modificação não é isolamento de segurança.** | `scripts/run_sandbox_selfmod_validation.py:62-80` apenas ajusta variáveis de ambiente e executa `compileall`, healthcheck e pytest no runner/workspace. O workflow `.github/workflows/selfmod-sandbox.yml:21-51` faz checkout e instala dependências; não há evidência de container rootless, seccomp, filesystem somente leitura, egress negado ou remoção de credenciais. | Executar código não confiável em ambiente efêmero sem segredos, com identidade read-only, rede negada por padrão, filesystem mínimo, seccomp/AppArmor e limites de recursos. Até lá, não chamar o processo de sandbox de segurança. |
| P0-6 | **Há um segundo loop oculto com auto-instalação e alteração de crontab.** | `modules/atena_organism.py:127-151` copia código para `~/.atena_core/atena_organism.py` e altera o crontab para execução a cada 15 minutos; `:195-209` mantém um loop com heartbeat de 15 segundos. Esse caminho não usa o PEC, ToolBroker ou LLMRouter do ciclo principal. | Remover auto-instalação e alteração silenciosa de crontab; usar um único scheduler/serviço com opt-in, uninstall, permissões mínimas, lease e healthcheck. Isolar o organismo como demonstração se não for parte do produto. |
| P0-7 | **A base de dados tem risco de divergência, perda silenciosa e recuperação incompleta.** | `core/memory_store.py:367-382` atualiza `episodes.status/confidence` sem atualizar `record_json/content_hash`; `get()` lê JSON e `retrieve_context()` lê colunas relacionais. `ConsequenceMemory` usa `INSERT OR IGNORE` em `core/consequence_memory.py:208-223`, sobrescreve concorrência em `:225-241` e gera IDs aleatórios em `consolidate_lessons()` (`:272-286`). Exports/imports são parciais (`memory_store.py:384-391`, `consequence_memory.py:311-340`) e KnowledgeBase não oferece restore completo. | Escolher fonte canônica, usar transações/versionamento ou eventos append-only, rejeitar conflitos de payload, tornar lições idempotentes, centralizar migrações, implementar backup consistente e testar restore em ambiente isolado. |
| P0-8 | **O caminho de release tem bloqueadores objetivos.** | `.github/workflows/atena-evolution-agent.yml:189-192` e `.github/workflows/atena-qlora-1.5b.yml:203-211` contêm linhas isoladas `PY`, potencialmente tornando os workflows inválidos. `render.yaml:6` aponta para `uvicorn api.main:app`, mas `api/main.py:96-99` referencia `ChatRequest` sem definição/import e o handler `/api/chat` contém `pass`; a importação local também falhou por `ModuleNotFoundError: discord`. | Validar YAML e expressões antes do merge; corrigir e testar o contrato da API em instalação limpa; bloquear deploy até `import api.main`, startup, readiness e smoke HTTP funcionarem. |

### P1 — arquitetura, produção e governança

| ID | Achado consolidado | Evidência concreta | Ação requerida |
|---|---|---|---|
| P1-1 | **Existem duas implementações incompatíveis do PlannerExecutorCritic e vários orquestradores.** | `core/agent_plan_loop.py` é o PEC conectado, com handlers reais, rollback e critic de evidência. `core/planner_executor_critic.py` contém `decompose_goal/run_planner_loop` e heurística de risco; `modules/atena_enterprise_advanced_mission.py` e parte dos testes usam a implementação legada. Também existem `UnifiedAgentCycle`, `objective_cycle_runner`, `TaskManager`, `atena_organism` e `multi_agent_orchestrator`. | Tornar `core/agent_plan_loop.py` o contrato canônico, mover a heurística para `RiskAssessor`, criar fachada de compatibilidade `deprecated` e colocar todos os fluxos atrás de uma `MissionOrchestrator` única. |
| P1-2 | **O ciclo agendado não tem scheduler autoritativo, lease ou idempotência transversal.** | `scripts/atena_scheduled_cycle.py:421-465` monta duas etapas fixas; `TaskManager` agenda futuro com `asyncio.create_task` em `modules/atena_tasks.py:896-915`, mas no startup enfileira pendências em `:759-765`, sem evidência de filtro por horário. Há Actions a cada 30 minutos, outros schedulers e workflows concorrentes. | Persistir `next_run`, estado, tentativas e misfire policy; usar lease/concurrency group, heartbeat, chave idempotente por ciclo, backoff, start/end e recuperação que só enfileire tarefas cujo horário chegou. |
| P1-3 | **A política de risco pode ser rebaixada pelo chamador.** | `ToolCall` possui `requested_risk` e `requires_confirmation` em `core/tool_contracts.py:14-21`; `ToolBroker.dispatch` em `core/tool_broker.py:166-204` valida a policy por nome e não reconcilia esses campos. `register_executor/bind_tool` em `:148-164` permitem rebinding em runtime. `tasker.open_app` aparece como `device_side_effect` com `confirmation=False` em `:126-129`. | Derivar risco e aprovação somente da policy imutável; exigir monotonicidade, capability token e aprovação ligada ao digest; separar registro de executor de autorização e expor capabilities como `unavailable`, `mock` ou `real`. |
| P1-4 | **O critic valida presença de evidência, não o critério de sucesso.** | `PlannerExecutorCritic._extract_evidence` apenas coleta `output.evidence/evidence_refs`; a aceitação depende da existência da lista. No ciclo, a checagem adicional é `critic accepted` e `web_output.items` não vazio em `scripts/atena_scheduled_cycle.py:452-457`. | Modelar critérios como predicados tipados, com validator por ferramenta, proveniência, timestamp, conteúdo mínimo, freshness e independência de fonte. |
| P1-5 | **O roteamento LLM tem bypass e contratos assíncronos inconsistentes.** | `scripts/atena_scheduled_cycle.py:377-398` instancia `AtenaLLMRouterAdvanced` e, em falha, chama Ollama diretamente, bypassando singleton, quota, cache e métricas. `generate_sync` em `core/atena_llm_router.py:977-989` cria uma tarefa e chama `future.result()` imediatamente dentro de loop ativo. `generate_stream` (`:942-975`) não compartilha todas as proteções de `generate`. | Injetar uma única `LLMRouterFacade`; concentrar fallback, quota, circuit breaker, cache, métricas, timeout e cancelamento; separar rigorosamente `generate_async` de `generate_sync`; cobrir streaming e falhas em testes de contrato/caos. |
| P1-6 | **O schema é fragmentado e não tem versão efetiva única.** | A fotografia de `atena_evolution/memory.sqlite3` estava com `PRAGMA integrity_check=ok`, WAL e 44 snapshots de `learning_progress`, mas `user_version=0` e sem tabelas `episodes`, `provenance`, `evidence_links`, `research_intents`, `source_health` ou `consequence_*`. Stores executam `CREATE TABLE IF NOT EXISTS` independentemente; somente `MemoryStore` registra schema migration versão 1. | Criar migrador transacional único, `user_version`/tabela de versões, lock de migração, compatibilidade mínima e startup que falhe explicitamente em schema incompleto. |
| P1-7 | **CI, dependências e testes não formam um gate reprodutível.** | Embora `pyproject.toml` declare cobertura mínima de 80%, Ruff, mypy, Pylint, Bandit e pytest configurado, `.github/workflows/atena-ci-and-update.yml:89-97` executa apenas `python -m pytest -q`. `requirements-pinned.txt` usa ranges, há divergência com `requirements.txt` e `pyproject.toml`, e não há lockfile Python. A coleta alcançou 531 testes antes de cinco erros, incluindo `structlog` ausente e `asyncio_mode` desconhecido. | Adotar uma fonte canônica com lockfile e hashes; separar gates de lint, tipos, segurança, testes, integração e cobertura; testar instalação limpa em Python 3.10–3.12; fazer falhar na coleta quando plugin/configuração estiver ausente. |
| P1-8 | **Não existe readiness nem promoção/deploy canônico com rollback verificável.** | `/healthz` em `api/main.py:67-69` sempre retorna `healthy`; não há `/livez`, `/readyz` nem `healthCheckPath` em `render.yaml:1-16`. Há Render, Vercel, Pages, systemd e SSH, mas sem smoke pós-deploy comum. `core/atena_smart_rollback.py:43-218` mantém snapshots locais e não é chamado pelos deploys; o workflow QLoRA reinicia serviço sem troca atômica/probe/rollback. | Definir um alvo primário; buildar uma vez e promover artefato imutável; adicionar liveness/readiness, smoke pós-deploy, versão/commit, symlink `current`, retenção de releases e rollback automático ou aprovado. |
| P1-9 | **Permissões e supply chain são amplas e não determinísticas.** | Vários workflows usam `contents: write` e/ou `pull-requests: write`; `auto-promote-main.yml:17-19,80-90` pode fazer merge automático. Actions usam referências mutáveis, dependências têm ranges, e há `pip install --upgrade pip`, `curl https://ollama.com/install.sh` e `git clone` de `llama.cpp`. | Aplicar least privilege por job, branch/environment protection, pinning de actions por SHA, lockfile com hashes, SBOM, scanner de secrets/dependências e aprovação separada para promoção. |
| P1-10 | **O workflow Telegram publica dados de usuário com token de escrita.** | `.github/workflows/atena-telegram-listener.yml:1-19,98-131` usa `contents: write` e faz push para `atena/autoevolution`; o listener registra prompt/resposta em `scripts/atena_telegram_chat.py:786-793`; a sanitização mostrada é apenas regex de token Telegram. | Remover push automático; usar artefato privado ou PR isolado com revisão; redigir PII, chaves, URLs com credenciais e instruções; impedir consumo automático como treino/memória. |
| P1-11 | **Persistência do ciclo usa dual-write com falha parcial tolerada.** | `scripts/atena_scheduled_cycle.py:551-598` grava JSON legado, proposta e SQLite; quando SQLite falha, registra status e só relança se `SQLITE_REQUIRED`. | Definir registro canônico e outbox idempotente com estados `pending/committed/failed`; reconciliar legados a partir da fonte canônica e falhar healthcheck quando promoção de evidência/progresso não for consistente. |
| P1-12 | **Testes são majoritariamente unitários e não cobrem o caminho real.** | O inventário encontrou 141 arquivos em `tests/unit` e apenas dois arquivos diretamente em `tests`, sem suites equivalentes de integração/e2e. Não há cobertura real consistente de `/api/chat`, deployment, Telegram real, Supabase, corrida de scheduler ou restore completo. | Criar testes de contrato HTTP, integração com serviços efêmeros, replay, concorrência, crash entre writes, SSRF, shell injection, prompt injection, fallback LLM e smoke pós-deploy. |

### P2 — robustez, medição e manutenção

| ID | Achado consolidado | Evidência concreta | Ação requerida |
|---|---|---|---|
| P2-1 | **Retenção e auditoria cobrem somente parte do histórico.** | `core/atena_memory_maintenance.py:34-58` e `core/atena_memory_relevance_audit.py:32-67` operam somente sobre `experiences`; não há política uniforme para episódios, evidências, KnowledgeBase, consequências, learning progress ou lesson usage. | Criar TTL por classe, legal hold, proteção por referências, arquivamento, dry-run, ledger de deleções e backup obrigatório antes de purge. |
| P2-2 | **Métricas de consequência e aprendizagem podem ser enviesadas ou não verificáveis.** | `ConsequenceMemory.metrics()` usa apenas `recent(500)` em `core/consequence_memory.py:351-365`; `learning_progress.py:76-92` grava `lesson_usage.applied=0` sem API correspondente; `record_cycle()` aceita contadores fornecidos pelo chamador, sem reconciliação. | Declarar janelas e denominadores, agregar por período/tarefa/modelo/benchmark, registrar eventos `consulted/applied/validated`, vincular ciclo/lição e reconciliar com episódios. |
| P2-3 | **Benchmarks não garantem comparabilidade.** | `LearningProgress` filtra por `benchmark_version`, mas modelo, prompt, task hash e seed ficam em `payload_json`; `benchmark_summary()` compara primeiro/último score por timestamp/rowid. | Criar manifesto de benchmark com conjunto de tarefas, hash, prompt/modelo, seed, ambiente e protocolo; bloquear agregações incompatíveis e reportar variância/amostra. |
| P2-4 | **KnowledgeBase pode perder diversidade de fontes e a FTS não tem reconciliação.** | `core/knowledge_base.py:103-112` deduplica globalmente por `content_hash`, ignorando URL/domínio/tópico/fonte; `knowledge_fts` é preenchida manualmente, sem orphan-check ou métrica de fallback, e o fallback em `:130-145` pesquisa apenas o primeiro termo. | Separar identidade do conteúdo de ocorrência da fonte; preservar URL/data/domínio e confirmação/contradição; criar rebuild/reconcile FTS e medir recall@k, MRR, diversidade e latência. |
| P2-5 | **Concorrência e constraints relacionais são frágeis.** | `MemoryStore.append()` calcula `MAX(sequence)+1` fora de escrita imediata (`core/memory_store.py:167-168`) e permite `link_previous=False`; stores relacionais dependem principalmente de validação Python, sem CHECKs/FKs equivalentes. | Usar contador transacional e retry, restringir quebra de cadeia a import explícito, adicionar CHECKs/FKs/NOT NULL e um `integrity doctor`. |
| P2-6 | **Integrações e observabilidade são locais e incompletas.** | `scripts/sync_memory_to_supabase.py` espera tabela `memory` com colunas que não aparecem na fotografia padrão do SQLite; `main.py:27-29` usa logging básico e `monitoring_health.py` grava em SQLite local, sem evidência de métricas/traces/alertas centralizados. | Criar adaptador de schema versionado e cursor idempotente; adicionar logs JSON, IDs de correlação, OpenTelemetry, Prometheus/Sentry e alertas para erros, latência, atrasos e falhas parciais. |
| P2-7 | **O estado do provider e o streaming não são comparáveis ao caminho normal.** | `connection_status` retorna `internet_ok=False` fixo em `core/atena_llm_router.py:837-842`, apesar de `_has_internet` em `:791-799`; descoberta local usa HTTP síncrono em `:746-754`. | Separar liveness/readiness, tornar discovery assíncrono ou isolado, indicar providers/quotas/circuitos e compartilhar lifecycle de seleção entre streaming e geração comum. |
| P2-8 | **GitHub Pages publica o checkout inteiro.** | `.github/workflows/static.yml:28-30` usa `upload-pages-artifact` com `path: .`. | Gerar diretório de distribuição explícito e testar exclusão de `.env`, SQLite, logs, configuração e artefatos internos. |

### P3 — limpeza e compatibilidade

| Achado | Evidência | Tratamento |
|---|---|---|
| Histórico de pesquisas pode ser sobrescrito | `KnowledgeBase.record_research()` usa `INSERT OR REPLACE` em `core/knowledge_base.py:157-161`. | Substituir por inserção com conflito explícito ou tabela de versões; registrar reexecuções separadamente. |
| Estado de conectividade e nomes de APIs estão dispersos | Há `AtenaLLMRouter`, `AtenaLLMRouterAdvanced`, `get_router` e chamadas diretas. | Manter adapters legados apenas com marcação `deprecated`, matriz de consumidores e documentação de migração. |
| Configuração e documentação divergem do CI efetivo | README e `pyproject.toml` anunciam controles que o workflow principal não executa. | Atualizar documentação depois que os gates forem implementados; não usar a configuração declarada como evidência de controle ativo. |

## Arquitetura-alvo proposta

A arquitetura abaixo é uma proposta de convergência, não uma descrição do estado atual.

```text
                         +-------------------------------+
                         | Entradas                       |
                         | Actions batch | API | Telegram |
                         | Worker | CLI                  |
                         +---------------+---------------+
                                         |
                         +---------------v---------------+
                         | Admission / Auth / Validation |
                         | actor, tenant, input limits   |
                         +---------------+---------------+
                                         |
              +--------------------------v--------------------------+
              | MissionOrchestrator                                 |
              | Mission -> Plan -> Execute -> Critique -> Persist   |
              | cycle_id, trace_id, plan fingerprint, idempotency  |
              +---------+----------------+----------------+----------+
                        |                |                |
              +---------v------+ +-------v--------+ +-----v---------+
              | Durable        | | LLMRouterFacade | | Evidence      |
              | Scheduler      | | quota/circuit/  | | Guard +       |
              | lease/misfire/ | | fallback/stream | | Success       |
              | retry          | | metrics         | | Verifier      |
              +---------+------+ +-------+--------+ +-----+---------+
                        |                |                |
                        +----------------v----------------+
                        | Canonical Planner / RiskAssessor|
                        | core.agent_plan_loop             |
                        +----------------+----------------+
                                         |
                         +---------------v---------------+
                         | Policy Graph + Approval Ledger |
                         | immutable capabilities, actor, |
                         | payload digest, TTL, one-shot  |
                         +---------------+---------------+
                                         |
                         +---------------v---------------+
                         | ToolBroker / Effect Gateway    |
                         | idempotency, timeout, audit,    |
                         | side_effect real, state unknown|
                         +-----+-------------------+------+
                               |                   |
                 +-------------v----+     +--------v----------------+
                 | Read executors   |     | Effect executors         |
                 | memory / web     |     | Tasker / HA / GitHub     |
                 | SSRF-safe fetch  |     | isolated identities     |
                 +-------------+----+     +--------+----------------+
                               |                   |
                               +---------+---------+
                                         |
                         +---------------v---------------+
                         | Persistence + Outbox           |
                         | schema versionado, transações, |
                         | evidência, proveniência,        |
                         | backup/restore, retention      |
                         +---------------+---------------+
                                         |
                         +---------------v---------------+
                         | Trace / Metrics / Audit         |
                         | logs JSON, OpenTelemetry,       |
                         | Prometheus/Sentry, replay       |
                         +---------------------------------+
```

### Invariantes da arquitetura-alvo

1. **Um único orquestrador de missão.** Telegram, evolução, pesquisa, API e multiagente devem ser adaptadores de uma mesma interface `Mission -> Plan -> CycleResult`.
2. **Um único PEC canônico.** A implementação legada deve ser somente compatibilidade temporária e não pode ser escolhida por novos consumidores.
3. **Todo efeito passa pelo gateway.** Não deve existir chamada direta de Tasker, Home Assistant, GitHub ou outro downstream fora do broker/gateway.
4. **A policy é autoridade.** O chamador não pode reduzir risco, confirmação, escopo ou sandbox declarados pela capability.
5. **Aprovação é um objeto verificável.** Ela deve conter ator, ferramenta, recurso, digest dos argumentos, expiração, uso único e estado transacional.
6. **Nenhum retry cego.** Operações externas devem possuir chave idempotente e tratamento explícito de resultado desconhecido.
7. **Conteúdo externo é dado não confiável.** Ele deve ser separado do prompt de controle, não pode autorizar ações e só pode entrar em memória/treino após curadoria e proveniência.
8. **Uma fonte canônica de persistência.** JSON legado, JSONL e índices devem ser derivados ou reconciliáveis, não fontes concorrentes de verdade.
9. **Um scheduler autoritativo.** Cada ciclo tem `cycle_id`, `next_run`, lease, heartbeat, tentativa, misfire policy e estado final.
10. **Release verificável.** Cada deploy precisa de artefato imutável, versão/commit, readiness, smoke, observabilidade e rollback testado.

## Ferramentas e componentes a criar

Os nomes são propostas de implementação e não representam ferramentas já existentes no repositório.

| Prioridade | Ferramenta/componente | Finalidade e critério de conclusão |
|---|---|---|
| P0 | `workflow_security_guard` | `actionlint`, `yamllint`, detecção de interpolação shell insegura, permissões excessivas, secrets em histórico/logs, actions por SHA e publicação de artefatos somente permitidos. |
| P0 | `policy_enforcing_effect_gateway` | Gateway único para Tasker, Home Assistant, Telegram e GitHub com capability token, ator, digest, aprovação, TTL, rate limit, idempotência e auditoria. |
| P0 | `approval_ledger` | Ledger transacional append-only para `pending/approved/consumed/expired/failed/unknown`, deduplicação e reconciliação. |
| P0 | `ssrf_safe_fetcher` | Allowlist de host/path, HTTPS, bloqueio de IP privado/loopback/metadata, redirects revalidados, limites e egress controlado. |
| P0 | `untrusted_content_guard` | Envelope tainted, separação de dados e instruções, redaction, detecção de prompt injection, proveniência e testes adversariais. |
| P0 | `isolated_code_runner` | Execução rootless e efêmera, rede negada, filesystem mínimo, seccomp/AppArmor, limites de CPU/memória/processos e nenhum secret. |
| P0 | `durable_scheduler` | `next_run`, lease, idempotency key, heartbeat, attempts, misfire policy, retry/backoff e prevenção de sobreposição. |
| P0 | `memory_doctor` | Diagnóstico somente-leitura de migrações, PRAGMAs, hashes, paridade JSON/colunas, cadeias, órfãos, FTS, referências e duplicatas. |
| P0 | `schema_migrator_central` | Migração única e transacional para MemoryStore, KnowledgeBase, ConsequenceMemory e LearningProgress, com versão, lock, dry-run e compatibilidade mínima. |
| P0 | `memory_backup_restore` | SQLite Online Backup/WAL checkpoint, manifesto de schema/contagens/checksums, export completo, restore isolado e comparação automatizada. |
| P0 | `release_manager` | Release imutável, health/readiness probe, smoke pós-deploy, troca atômica, retenção de versões e rollback verificável para os alvos escolhidos. |
| P0 | `consequence_reconciler` | Detecção de conflitos de `episode_id`, lost updates, eventos sem hash, lições duplicadas e reconstrução por fingerprint estável. |
| P1 | `mission_orchestrator` | Contrato único para missão, plano, ferramentas, LLM, evidência, scheduler, resultado e trace; adapters para os fluxos existentes. |
| P1 | `capability_policy_graph_inspector` | Matriz efetiva ferramenta → executor → risco → confirmação → sandbox → side effect; identifica mocks, downgrades e bindings fora da policy. |
| P1 | `agent_trace_and_replay` | Correlação de ciclo, plano, etapas, ToolResult, evidências, modelo/provider, quotas e persistência; replay sem efeitos externos. |
| P1 | `evidence_success_criteria_verifier` | Predicados tipados, validação por ferramenta, freshness, independência, proveniência e conteúdo mínimo antes de aceitar o critic. |
| P1 | `llm_router_contract_chaos_harness` | Testes de seleção, quota, circuit breaker, fallback, streaming, cancelamento, sync/async, latência e custo. |
| P1 | `restore_and_concurrency_tests` | Testes de múltiplos escritores, WAL, crash entre writes, migração, restore, retries e conflitos de idempotência. |
| P1 | `retrieval_evaluation_suite` | Dataset fixo e métricas de recall@k, MRR, diversidade de fontes, exposição de expirados, fallback lexical e latência. |
| P1 | `source_provenance_reconciler` | Preserva ocorrências por URL/domínio/data, detecta deduplicação que eliminou fontes independentes e reconcilia FTS. |
| P1 | `dependency_lock_and_supply_chain` | Lock Python com hashes, SBOM, scanner de vulnerabilidades, pins de actions/commits/modelos e atualização por PR revisável. |
| P1 | `observability_stack` | Logs JSON, IDs de correlação, OpenTelemetry, Prometheus/Sentry, alertas de jobs, filas, erros, latência e freshness. |
| P2 | `retention_orchestrator` | TTL por classe, legal hold, retenção referencial, arquivamento, purge seguro, dry-run e ledger de deleções. |
| P2 | `learning_metrics_exporter` | Métricas por janela e dimensão para writes, conflitos, retrieval, evidência, outcomes, regressões, consulta/aplicação de lições e integridade. |
| P2 | `benchmark_manifest_validator` | Valida task-set, hash, prompt/modelo, seed, ambiente e protocolo antes de comparar runs. |
| P2 | `supabase_sync_adapter` | Adapta o schema canônico, valida pré-condições, usa cursor/idempotência e testa sync/restore em banco vazio e populado. |

## Roadmap em fases

### Fase 0 — contenção e decisão de release

Suspender ou restringir workflows que aceitam input em shell, escrita automática, auto-promoção ou execução de código não confiável. Remover secrets desnecessários dos jobs, corrigir a publicação de Pages, revisar `.env` rastreado e seu histórico, e rotacionar credenciais se a inspeção confirmar exposição. Bloquear efeitos reais atrás do gateway e marcar Tasker/GitHub como `mock` ou `unavailable` enquanto não houver executor governado. Remover o crontab oculto. Validar os 14 workflows e a importação/startup da API em árvore limpa.

### Fase 1 — CI e release determinísticos

Adotar lockfile Python com hashes, pinning por SHA, SBOM e scanners. Fazer o CI executar lint, tipos, segurança, testes, cobertura e coleta limpa. Corrigir `asyncio_mode`/plugins, dependências como `structlog` e os erros de import. Implementar `/livez` e `/readyz`, smoke HTTP pós-deploy, identificação de commit e um alvo primário de produção. Conectar o release manager a deploy, probe e rollback.

### Fase 2 — convergência da arquitetura de agentes

Criar `MissionOrchestrator`, escolher `core.agent_plan_loop.py` como PEC canônico e depreciar a implementação legada. Consolidar o LLMRouter em uma fachada injetada. Implantar scheduler durável com lease, idempotência e heartbeat. Colocar Telegram, evolução, pesquisa, API e multiagente como adapters do contrato comum. Criar trace ponta a ponta e replay sem efeitos.

### Fase 3 — governança de ferramentas e evidências

Implementar policy graph, gateway de efeitos e approval ledger. Corrigir monotonicidade de risco, capability binding e envelope de `side_effect`. Implementar coletor SSRF-safe e guard de conteúdo não confiável. Transformar critérios de sucesso em predicados verificáveis e separar evidência bruta de memória/treino aprovado.

### Fase 4 — dados, recuperação e concorrência

Centralizar migrações e versão de schema. Corrigir paridade JSON/relacional, conflitos de `episode_id`, lost updates, lições não idempotentes e sequência concorrente. Implementar backup/restore com restore drill, retenção referencial e `memory_doctor`. Preservar ocorrências de fontes, reconciliar FTS, validar benchmarks e adaptar o sincronizador Supabase.

### Fase 5 — habilitação controlada de efeitos

Somente após aprovação dos gates anteriores, implementar executores reais individualmente, cada um com escopo mínimo, dry-run, idempotência nativa, timeout, compensação, confirmação forte, auditoria e teste de reconciliação. Promover primeiro em staging/canário, com observabilidade e rollback. Manter escrita desabilitada por padrão e remover caminhos diretos e schedulers duplicados após migração.

## Caveats da auditoria

- A análise fornecida é predominantemente estática. Os relatórios recomendam testes dinâmicos adicionais de SSRF, shell injection, prompt injection, replay, concorrência, fallback LLM e deploy.
- Os resultados de testes dependem da configuração. Uma execução focada com `pytest` temporário totalizou **21 passed**; a execução canônica falhou antes da coleta por `Unknown config option: asyncio_mode`. Outra coleta alcançou **531 testes**, mas parou com cinco erros de import/configuração, incluindo `structlog` ausente. Isso indica drift do ambiente, não uma única taxa de aprovação.
- A fotografia do SQLite reportada estava íntegra segundo `PRAGMA integrity_check=ok`, mas tinha schema parcial e `user_version=0`; integridade física não prova consistência semântica nem completude do schema.
- A presença de `.env` no índice Git foi observada, mas os relatórios não confirmaram que o arquivo contém valores secretos reais. A verificação e eventual rotação são urgentes, porém a exposição não deve ser afirmada como fato confirmado.
- O workspace auditado tinha alterações locais e arquivos não rastreados pré-existentes. Nenhum arquivo do repositório foi alterado pelos auditores; foram usados arquivos temporários de auditoria.

## Referências internas

As evidências e caminhos citados acima foram transcritos dos quatro relatórios fornecidos para esta auditoria e se referem ao repositório `/home/ubuntu/Atena-IA`.

[1]: file:///home/ubuntu/Atena-IA "Repositório Atena-IA auditado"
[2]: file:///home/ubuntu/Atena-IA/.github/workflows "Workflows GitHub Actions auditados"
[3]: file:///home/ubuntu/Atena-IA/core "Componentes de núcleo auditados"
[4]: file:///home/ubuntu/Atena-IA/scripts "Scripts operacionais auditados"
