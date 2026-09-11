# Roteador multi-API com failover da Atena

A Atena agora mantém a seleção de provider por tarefa e um ledger SQLite local para quotas e cooldowns. Quando um provider responde com `429`, quota esgotada, timeout, sobrecarga ou erro transitório, o roteador registra o incidente e tenta o próximo provider permitido para aquela categoria.

## Providers e ordem

A matriz está em `core/task_routing.py`:

| Tarefa | Preferência | Fallback |
|---|---|---|
| Conversa/Telegram | local | Gemini, Anthropic |
| Conteúdo privado | local | nenhum por padrão |
| Pesquisa web | Gemini | Anthropic, local |
| Código/evolução GitHub | Anthropic | Gemini, local |
| Multimodal/voz | Gemini | Anthropic, local |

O fallback não é uma autorização para executar ferramentas. Ele só escolhe um modelo para produzir uma resposta; Tasker, GitHub, Calendar, Sheets, mensagens, chamadas e deploy continuam protegidos pelas políticas próprias.

## Quotas locais

O ledger está em:

```text
atena_evolution/provider_quota.sqlite3
```

Configure limites locais por dia. Zero significa que não foi configurado limite local para aquele campo; isso não significa que o provedor não tenha limite próprio.

```bash
ATENA_PROVIDER_QUOTA_DB=/home/ubuntu/Atena-IA/atena_evolution/provider_quota.sqlite3
ATENA_GEMINI_DAILY_REQUESTS=100
ATENA_GEMINI_DAILY_TOKENS=500000
ATENA_GEMINI_DAILY_USD=2.00
ATENA_ANTHROPIC_DAILY_REQUESTS=50
ATENA_ANTHROPIC_DAILY_TOKENS=200000
ATENA_ANTHROPIC_DAILY_USD=2.00
ATENA_OPENAI_DAILY_REQUESTS=50
ATENA_OPENAI_DAILY_TOKENS=200000
ATENA_OPENAI_DAILY_USD=2.00
```

Os limites são uma barreira local conservadora. O roteador não consegue conhecer com segurança a quota restante de todos os provedores sem consultar endpoints autenticados específicos; por isso, ele combina contagem local com códigos HTTP e mensagens de quota retornados pela API.

## Cooldown e failover

Um erro com `429` ou `quota` coloca o provider em cooldown de cinco minutos. Erros transitórios como `408`, `500`, `502`, `503`, `504`, timeout e sobrecarga usam cooldown de 45 segundos. A requisição é então tentada no próximo provider da ordem, desde que ele esteja configurado, saudável e dentro do limite local.

Erros de autenticação ou de formato não são mascarados como quota. Eles devem ser corrigidos na configuração da chave ou do modelo antes de habilitar aquele provider.

## Auditoria

Consulte o uso local:

```bash
sqlite3 atena_evolution/provider_quota.sqlite3 \
  'select provider,day,requests,tokens,usd,cooldown_until,last_error from provider_usage;'
```

Não grave chaves, prompts privados completos ou respostas sensíveis no ledger.

## Configuração das APIs

```bash
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
ATENA_OPENAI_MODEL=...
ATENA_ANTHROPIC_MODEL=claude-fable-5
ATENA_GEMINI_MODEL=gemini-3.7-flash
```

As chaves devem ser fornecidas pelo arquivo protegido do systemd ou pelos secrets do GitHub Actions. Nunca coloque uma chave em `pyproject.toml`, workflow, issue, log ou Pull Request.

## LiteLLM e OpenRouter

A implementação nativa foi escolhida primeiro para preservar o controle da Atena sobre privacidade, memória, Tasker e auditoria. O [LiteLLM](https://docs.litellm.ai/docs/proxy/reliability) é uma alternativa open source para centralizar chamadas, budgets, rate limits e provider failover. O [OpenRouter](https://openrouter.ai/docs/guides/routing/model-fallbacks) oferece roteamento hospedado e fallbacks entre providers/modelos, mas adiciona uma camada externa e uma política própria de dados e custos.

Se LiteLLM for adotado depois, ele deve ficar atrás da mesma política de tarefas da Atena e não substituir as confirmações de ações. A primeira versão não instala um proxy adicional: o failover já ocorre no processo da Atena e no ledger local.
