# Auditoria completa da Atena — 13/08/2026

## Resumo executivo

A Atena possui uma base ampla e funcional: memória episódica em SQLite com proveniência, pesquisa web controlada, Telegram, Calendar/Sheets, Tasker com HMAC e nonce, monitoramento de ofertas, roteamento multi-API, quotas locais, workflows agendados e fluxo de evolução por Pull Request. A suíte completa, depois da instalação das dependências declaradas, terminou com **485 testes aprovados e 3 testes pulados** porque `torch` não está instalado no ambiente.

A conclusão principal é que a Atena está mais forte como **plataforma de agente auditável** do que como modelo autônomo. A qualidade da resposta depende principalmente do modelo disponível, das evidências recuperadas, da memória e das regras de aprovação. O ciclo autônomo da `main` ainda usava diretamente o Ollama pequeno; essa integração foi corrigida no PR #19 para que a evolução use o roteador multi-API, com fallback local.

## Achados comprovados

| Área | Estado observado | Risco |
|---|---|---|
| Testes | 485 passados, 3 pulados por ausência de `torch` | Médio: pipeline RLHF real não é exercitado localmente |
| Dependências | `pip check` sem dependências quebradas depois de instalar `requirements.txt` | Baixo |
| Evolução | A `main` usava `qwen2.5:3b-instruct` diretamente | Alto: raciocínio limitado para propostas complexas |
| Correção | PR #19 roteia `github_evolution` por Anthropic → Gemini → Ollama | Baixo após merge e configuração dos secrets |
| Memória | SQLite, hashes, episódios e evidence links presentes | Médio: promoção deve continuar exigindo múltiplas evidências |
| APIs | Circuit breaker, rate limiter, quotas e fallback local presentes | Médio: quota restante real depende de sinais retornados pelo provedor |
| Tasker | HMAC, timestamp, nonce, fila e aprovação consumível presentes | Médio: gateway requer servidor persistente HTTPS |
| Capacidades | Descoberta estática, mas execução dinâmica importava módulos | Alto: módulos com efeitos externos poderiam ser carregados sem política explícita |
| Correção | `ATENA_CAPABILITY_ALLOWLIST` agora é obrigatória para executar módulos | Baixo após merge |
| Ofertas | Workflow fazia checkout de `atena/autoevolution`, que não continha `store_discount_alert.py` | Alto: execução falhou com `file not found` |
| Correção | Workflow Steam agora faz checkout de `main` e publica somente o estado na branch de memória | Baixo após merge |
| Telegram | Smoke tests anteriores passaram | Baixo; processo contínuo ainda depende de systemd/servidor persistente |
| GitHub | PRs antigos ainda abertos podem causar fragmentação e conflitos | Médio |
| Produção | CI principal verde; Vercel reportou rate limit de deployment | Médio: código na `main`, deploy visual externo não confirmado |
| Recursos locais | Cerca de 3,8 GiB RAM e sem GPU NVIDIA; Ollama tem `llama3.2` e `qwen2.5:3b-instruct` | Alto para modelos locais grandes |

## Melhorias aplicadas nesta auditoria

A primeira melhoria faz o ciclo autônomo chamar `AtenaLLMRouterAdvanced` com `task_type=github_evolution`. A seleção passa a ser Anthropic, Gemini e Ollama, nessa ordem, respeitando providers configurados, health status, quotas locais e cooldowns. O ciclo grava `provider`, `model` e `task_type` no JSON/SQLite e a notificação do Telegram passa a exibir o provider efetivamente utilizado.

A segunda melhoria corrige o workflow de ofertas. O checkout de uma branch de memória desatualizada foi substituído por checkout da `main`; a persistência continua sendo publicada separadamente em `atena/autoevolution`. Essa causa foi confirmada pelos logs do GitHub Actions, que registraram `can't open file scripts/store_discount_alert.py`.

A terceira melhoria adiciona uma allowlist explícita ao capability registry. `run_capability()` agora rejeita qualquer capacidade que não esteja em `ATENA_CAPABILITY_ALLOWLIST`. O padrão vazio bloqueia execução de módulos com efeitos externos, como Hydra, até que haja autorização consciente.

## Recomendações priorizadas

| Prioridade | Recomendação | Impacto | Esforço | Estado |
|---|---|---:|---:|---|
| P0 | Mesclar PR #19 depois do CI e configurar somente as chaves de providers aprovados | Muito alto | Baixo | Em andamento |
| P0 | Manter confirmação para mensagens, chamadas, Calendar, Sheets, Tasker e deploy | Muito alto | Médio | Implementado; ampliar cobertura |
| P0 | Não permitir execução de módulos sem allowlist, sandbox e testes | Muito alto | Baixo | Implementado no PR #19 |
| P1 | Adicionar teste de contrato do ciclo para verificar `provider/model` e fallback | Alto | Médio | Recomendado |
| P1 | Criar health check persistente do bot Telegram e alerta quando o systemd cair | Alto | Médio | Recomendado |
| P1 | Adicionar retenção/consolidação de memória por idade, duplicidade e qualidade da evidência | Alto | Médio | Parcialmente implementado |
| P1 | Separar completamente artefatos de memória gerados de código-fonte em branches e PRs | Alto | Médio | Parcialmente implementado |
| P1 | Corrigir/monitorar o workflow Steam após o merge da correção | Alto | Baixo | Corrigido no PR #19 |
| P2 | Instalar `torch` somente em job dedicado para desbloquear os 3 testes RLHF | Médio | Médio/alto | Pendente por RAM e tempo |
| P2 | Criar benchmark temporal independente com conjunto rotativo e avaliador externo | Alto | Médio | Recomendado |
| P2 | Registrar custo estimado por provider, latência p50/p95 e taxa de fallback | Alto | Médio | Quotas locais implementadas; métricas de custo pendentes |
| P2 | Adicionar revisão de licenças e commit fixo para qualquer projeto pesquisado no X | Alto | Médio | Parcialmente implementado |
| P3 | Consolidar PRs antigos e fechar branches obsoletas | Médio | Baixo | Pendente |
| P3 | Adicionar painel operacional para saúde do Telegram, Ollama, APIs e workflows | Médio | Médio | Pendente |

## Configuração necessária para a evolução usar modelos remotos

Depois do merge do PR #19, a evolução usará APIs remotas somente se suas credenciais existirem no ambiente do job:

```text
ANTHROPIC_API_KEY
GEMINI_API_KEY
OPENAI_API_KEY (opcional)
```

Se as chaves estiverem ausentes, a rota permanece local. Os valores nunca devem aparecer em logs, arquivos versionados ou mensagens. O modelo local atual é adequado como fallback de privacidade e disponibilidade, mas não deve ser tratado como prova de inteligência geral.

## Limitações e próximos experimentos

Não foi possível confirmar a existência ou validade dos secrets do GitHub porque a credencial de automação recebeu HTTP 403 ao consultar a API de secrets. Isso não revela se os secrets estão ausentes; apenas impede sua inspeção programática. A presença de uma chave também não garante quota ou modelo habilitado.

Os três testes pulados dependem de `torch`. Instalar PyTorch no servidor com 3,8 GiB de RAM não é recomendado como configuração permanente; o melhor é executar essa avaliação em um job separado ou runner com mais memória.

O roteador pode detectar `429`, quota, timeout e erros transitórios, mas não consegue conhecer antecipadamente a quota restante de todo provedor. Para isso, seriam necessários endpoints autenticados específicos, além do ledger local.

## Critério de sucesso da evolução

Uma evolução só deve ser considerada real quando houver melhora repetida em benchmarks inéditos, segurança, factualidade, memória histórica e qualidade do código, com comparação contra um baseline fixo. Uma notificação ou proposta gerada não é evidência suficiente de inteligência crescente.
