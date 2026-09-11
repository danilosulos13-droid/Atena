# Batching de auditoria da Atena com Redis Streams

## Fluxo implementado

O módulo `core/atena_audit_queue.py` publica eventos `rag.query` em Redis Streams. O worker `scripts/atena_audit_worker.py` lê até `ATENA_AUDIT_BATCH_SIZE` eventos, aplica todos em uma única transação SQLite e somente depois confirma (`XACK`) as mensagens no Redis.

O lote agrega IDs repetidos em memória. Assim, se cinco consultas do mesmo lote acessarem o documento 42, o worker executa uma atualização com incremento 5, em vez de cinco transações separadas.

A configuração padrão é:

```text
ATENA_REDIS_URL=redis://localhost:6379/0
ATENA_REDIS_STREAM=atena:rag-events
ATENA_REDIS_GROUP=atena-audit-workers
ATENA_AUDIT_BATCH_SIZE=100
ATENA_AUDIT_BLOCK_MS=1000
```

Atenção: o worker deve usar um único escritor por arquivo SQLite. Redis pode ter vários consumidores, mas todos escreverem no mesmo SQLite recriaria a contenção.

## Esquema SQLite exato

A tabela `audit_log` deve conter a coluna `event_id`:

```sql
ALTER TABLE audit_log ADD COLUMN event_id TEXT;
```

A migração é aplicada automaticamente pelo `TenantMemoryRAG._init_db()` quando a coluna ainda não existe. Para bancos novos, a coluna já é criada na definição inicial da tabela.

A idempotência é garantida por este índice parcial único:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_id
ON audit_log(event_id)
WHERE event_id IS NOT NULL;
```

O índice parcial preserva eventos antigos cujo `event_id` é nulo e impede a inserção duplicada de eventos novos. O worker usa `INSERT OR IGNORE`. O contador de acesso só é incrementado quando a inserção do evento realmente ocorre.

Para verificar a migração:

```sql
PRAGMA table_info(audit_log);
PRAGMA index_list(audit_log);
SELECT event_id, COUNT(*)
FROM audit_log
WHERE event_id IS NOT NULL
GROUP BY event_id
HAVING COUNT(*) > 1;
```

A última consulta deve retornar zero linhas.

## Semântica de falha

O Redis Streams usa entrega pelo menos uma vez. Se o processo morrer antes do `XACK`, a mensagem será entregue novamente. O índice único por `event_id` torna essa repetição segura. O ACK acontece somente depois do commit SQLite; portanto, uma mensagem não confirmada será reprocessada, mas não duplicará a auditoria nem os contadores.

O worker não deve usar Redis Pub/Sub para esse fluxo, pois Pub/Sub não oferece histórico nem reprocessamento após uma queda do consumidor.

## Execução

Com Redis local disponível:

```bash
export PYTHONPATH="$PWD"
export ATENA_REDIS_URL=redis://localhost:6379/0
export ATENA_RAG_DB=atena_evolution/rag/atena_jarvis.sqlite3
export ATENA_AUDIT_BATCH_SIZE=100
python scripts/atena_audit_worker.py
```

Para ativar a publicação assíncrona no RAG:

```bash
export ATENA_ASYNC_AUDIT=1
```

Se a publicação falhar, o RAG retorna ao caminho síncrono para não perder a auditoria. Essa política pode ser alterada posteriormente para `fail-closed` em tenants ou operações que exigem confirmação de auditoria.

## Testes

Os testes unitários cobrem a migração, a unicidade de `event_id`, o incremento agregado e a repetição do mesmo evento. O teste de integração recomendado deve usar Redis real ou um serviço Redis temporário e validar o ciclo completo: `XADD`, `XREADGROUP`, transação SQLite e `XACK`.
