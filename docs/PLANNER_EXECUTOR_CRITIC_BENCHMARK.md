# Ciclo Planner–Executor–Critic e benchmark de abstração

## Objetivo

A Atena agora possui um ciclo explícito para transformar objetivos em etapas verificáveis, executar somente ferramentas registradas, interromper ações sem aprovação e revisar o resultado antes de declarar sucesso.

```text
objetivo → plano → validação → execução → observação/evidência → crítica → rollback ou conclusão
```

## Implementação

O módulo `core/agent_plan_loop.py` define `Plan`, `PlanStep`, `ToolSpec`, `ToolRegistry` e `PlannerExecutorCritic`.

Cada etapa deve indicar uma ferramenta da allowlist, parâmetros, risco, critérios de sucesso e, quando possível, uma ferramenta de rollback. Ferramentas sensíveis declaram `requires_approval=True`; o plano não pode remover essa exigência.

O executor não interpreta texto como shell, Python, JavaScript ou comando arbitrário. Ele chama somente handlers registrados no `ToolRegistry`. Em caso de falha, interrompe o plano e executa rollbacks registrados em ordem reversa. O crítico verifica falhas, evidências ausentes e falhas de rollback.

## Exemplo seguro

```python
from core.agent_plan_loop import Plan, PlanStep, PlannerExecutorCritic, ToolRegistry, ToolSpec

registry = ToolRegistry()
registry.register(ToolSpec(
    "read_status",
    lambda params: {"status": "ok", "evidence": ["status://android"]},
))

loop = PlannerExecutorCritic(registry)
plan = Plan(
    goal="consultar status",
    steps=(PlanStep("s1", "consultar", "read_status", success_criteria=("evidence",)),),
)
result = loop.execute(plan)
```

Uma mensagem, chamada, compra, deploy ou alteração de produção deve ser representada por uma ferramenta que exige aprovação. Sem aprovação identificada pelo chamador, o estado é `awaiting_approval` e nada externo é executado.

## Benchmark

O benchmark está em `scripts/abstraction_planning_benchmark.py` e não chama APIs. Ele contém tarefas de:

| Categoria | O que avalia |
|---|---|
| Abstração | Princípios, metáforas, premissas e limites |
| Planejamento | Dependências, critérios, obstáculos e segurança |
| Recuperação | Adaptação diante de falhas e critério de parada |
| Transferência | Aplicação de um princípio em domínio diferente |

Modo de prévia:

```bash
PYTHONPATH="$PWD" python scripts/abstraction_planning_benchmark.py --dry-run
```

Para avaliar respostas geradas por um modelo, forneça JSONL:

```json
{"task_id":"abstraction_invariant_transfer","response":"..."}
```

Execute:

```bash
PYTHONPATH="$PWD" python scripts/abstraction_planning_benchmark.py \
  --responses respostas.jsonl \
  --output benchmark-result.json
```

A pontuação é determinística: mede conceitos obrigatórios, padrões proibidos e uma taxa ponderada por tarefa. Ela é um gate de regressão, não uma prova de AGI ou compreensão plena.

## Próximas extensões

O planner pode ser conectado ao roteador LLM para gerar planos estruturados, mas a saída do modelo deve ser validada contra o schema antes de entrar no executor. O benchmark deve ser executado antes e depois de cada mudança, junto com replay de tarefas antigas para detectar esquecimento catastrófico. Nenhuma alteração deve ser promovida se melhorar abstração e causar regressão de segurança ou memória.
