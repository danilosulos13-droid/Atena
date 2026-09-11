# Memória de longo prazo, identidade e estado da Atena

## Diagnóstico atual

A Atena possui vários subsistemas de memória. O caminho canônico de episódios é `core/episodic_memory.py` + `core/memory_store.py`, com SQLite WAL, proveniência, confidence, evidências e cadeia de hashes. A recuperação ativa é feita por `core/memory_retrieval.py`, que combina relevância textual, confiança, evidência, verificação e recência.

Também existem subsistemas paralelos, como grafo persistente, índice vetorial/FAISS, RAG empresarial e o cofre de modelos. Eles podem ser úteis, mas não devem ser tratados como se estivessem automaticamente conectados ao caminho do Telegram ou do ciclo autônomo. Cada integração precisa de teste de contrato.

## Identidade e estado

O módulo `core/identity_state.py` acrescenta um armazenamento SQLite pequeno e auditável para preferências autorizadas, compromissos operacionais, estado atual, versão otimista e eventos append-only com hash encadeado.

```text
identidade → snapshot versionado → evento → hash → recuperação/verificação
```

O módulo não representa consciência nem personalidade autônoma. Ele preserva coerência operacional entre sessões, detecta escritores concorrentes obsoletos e acusa corrupção de estado.

## Healthcheck

Execute:

```bash
PYTHONPATH="$PWD" python scripts/memory_identity_healthcheck.py
```

O healthcheck importa os módulos centrais, cria bancos temporários, grava e verifica um episódio, testa a cadeia de identidade e informa se bancos de produção foram modificados. Ele não inicializa Telegram, Tasker, APIs externas, Docker, SSH ou módulos de infraestrutura.

Resultado esperado:

```json
{
  "episodic": {"ok": true},
  "identity": {"ok": true},
  "production_databases_modified": false
}
```

## Achado legado

O arquivo `atena_evolution/conversation_memory.json` contém uma entrada antiga cujo campo `assistant` é literalmente uma representação de coroutine. Esse artefato não é o caminho ativo do bot Telegram, que usa `data/telegram_sessions.json`, mas não deve ser promovido para memória canônica sem limpeza e validação. O healthcheck sinaliza o achado com `legacy_conversation_warning: true`.

A correção segura é arquivar o artefato e reconstruir a entrada a partir de uma resposta resolvida, nunca executar ou interpretar o texto como código. Não removi nem alterei o banco existente automaticamente.

## Política de manutenção

A memória bruta deve ser append-only. Consolidação, deduplicação e expiração devem criar registros derivados ou marcar estado de ciclo de vida; não devem apagar evidências sem backup. O histórico de identidade deve permanecer separado de conteúdo episódico e de segredos.

Antes de conectar o estado ao Telegram, use chat autorizado, retenção limitada, redaction de dados sensíveis e `/reset` para remover o contexto conversacional curto. Preferências persistentes devem ser explícitas e editáveis pelo usuário.
