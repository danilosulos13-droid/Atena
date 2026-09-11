# Memória de consequências da Atena

A memória de consequências registra o resultado observado após um plano ou ação. Ela complementa a memória episódica: a memória episódica responde ao que foi observado, enquanto esta camada registra se uma decisão funcionou, falhou, foi bloqueada, recebeu correção e produziu uma lição reutilizável.

## Modelo

Cada `ConsequenceEpisode` possui objetivo, plano, ações, resultado, evidências, feedback, confiança antes e depois, verificação de regressão e lições candidatas. O registro é validado por Pydantic e selado com SHA-256 sobre JSON canônico.

Os estados de resultado são `success`, `partial`, `failure`, `unknown` e `blocked`. Uma ação bloqueada não conta como sucesso. Feedback de usuário, teste, ferramenta, sistema ou revisor é armazenado separadamente do fato original.

## Uso básico

```python
from core.consequence_memory import (
    ActionRecord, ConsequenceEpisode, ConsequenceEvidence,
    ConsequenceFeedback, ConsequenceMemory, Lesson,
)

memory = ConsequenceMemory("atena_evolution/consequences.sqlite3")

episode = ConsequenceEpisode(
    task_id="telegram-smoke-2026-08-13",
    goal="validar a notificação Telegram",
    plan=["executar smoke test", "verificar resposta", "registrar evidência"],
    actions=[ActionRecord(name="telegram.send_test", status="executed")],
    outcome="success",
    outcome_summary="API retornou sucesso e o smoke test terminou verde",
    evidence=[ConsequenceEvidence(
        kind="test",
        claim="O envio foi aceito pelo endpoint",
        source="github-actions-run",
        independent=True,
    )],
    confidence_before=0.5,
    confidence_after=0.9,
    regression_checked=True,
    regression_score=0.98,
    lessons=[Lesson(
        statement="Executar smoke test antes de declarar a ponte Telegram operacional",
        applicability="integrações de notificação",
    )],
)

memory.record_episode(episode)
memory.append_feedback(
    episode.episode_id,
    ConsequenceFeedback(
        source="test",
        label="positive",
        text="Resultado reproduzido em execução independente",
        score=1.0,
    ),
)

print(memory.metrics().model_dump())
print(memory.verify_integrity())
```

## Consolidação

`consolidate_lessons()` agrupa lições equivalentes por hash normalizado. Uma lição só passa a `validated` quando possui evidência suficiente, sucesso observado e confiança acima do limite configurado. A consolidação não apaga episódios e pode ser repetida de forma segura.

```python
validated = memory.consolidate_lessons(
    min_evidence=2,
    min_confidence=0.65,
)
```

## Política de integração

O ciclo de autoevolução deve criar o episódio no início da tarefa, atualizar o resultado ao terminar e anexar feedback somente depois de uma evidência independente. Recomenda-se usar um banco separado durante o benchmark e o sandbox:

```text
/tmp/atena-consequence-test.sqlite3
```

O banco produtivo deve receber somente episódios completos e validados pelo quality gate. A memória de consequências não autoriza ações, não faz deploy e não substitui a confirmação necessária para Telegram, Tasker, chamadas, mensagens ou exclusões.

## Métricas

`metrics()` retorna total, sucessos, parciais, falhas, bloqueios, taxa de sucesso, taxa de feedback, taxa de evidência, variação média de confiança e taxa de episódios com regressão verificada. Essas métricas devem entrar no relatório de evolução e no avaliador baseline versus candidato.

## Busca ranqueada antes do planner

Use `search_validated_lessons()` para recuperar somente lições com status `validated`. O ranking combina sobreposição de termos, confiança, taxa de sucesso, quantidade de evidências e recência. O retorno inclui a pontuação e seus componentes para auditoria.

```python
ranked = memory.search_validated_lessons(
    "corrigir falha de código no Telegram",
    limit=5,
    min_confidence=0.65,
    applicability="código",
)
```

A busca deve ser feita antes do planner e os `lesson_id` recuperados devem ser gravados no episódio como `used_lesson_ids`. A nova experiência deve ser gravada separadamente em `generated_lessons`, evitando confundir memória consultada com aprendizado novo.

## Avaliação com e sem memória

O avaliador recebe dois JSONL pareados com os mesmos `task_id`:

```bash
python scripts/evaluate_consequence_memory_effect.py \
  --with-memory results/with_memory.jsonl \
  --without-memory results/without_memory.jsonl \
  --output results/consequence-effect-report.json
```

Cada linha deve conter `task_id` e `outcome`, por exemplo:

```json
{"task_id":"case-001","outcome":"success","critical_failure":false}
```

O relatório compara taxa de sucesso, regressões, tarefas melhoradas, tarefas pioradas, empates, uplift absoluto e intervalo bootstrap pareado. A decisão `promote_memory` só ocorre quando o limite inferior do intervalo de diferença é positivo e a taxa de regressão não aumenta. Caso contrário, a decisão é `hold`.

O avaliador não executa ferramentas e não grava no SQLite. Ele mede o efeito das lições; a execução dos casos deve ocorrer em sandbox separado, mantendo seed, modelo, prompt, ferramentas e ordem constantes entre as duas condições.
